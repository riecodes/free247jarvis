"""A prototype of near real-time ears and mouth: OpenAI's Realtime API hears the end of a request and reads replies aloud
as the audio arrives. Everything else is listener.py and voice.mjs as they are: the local wake word, the router (Jev,
then Haiku over the notes, then the orch on Opus), the follow-up window and the voice data.

Run instead of listener.py with VOICE_LISTENER=realtime.py in .env. Without OPENAI_API_KEY it is listener.py. When a
turn or a reply fails, the listener's own end of speech, speech to text and voice take over.

  python realtime.py measure request.wav    the real timings of one clip, for a few tenths of a US cent; plays nothing
"""
import base64
import json
import os
import queue
import sys
import threading
import time

import numpy as np

import listener

URL = "wss://api.openai.com/v1/realtime?model={model}"
MODEL = "gpt-realtime-2.1-mini"  # only reads replies aloud; the thinking is Haiku's and Opus's
RATE = 24000  # the rate of its audio, in and out
FIRST_SOUND = 4  # seconds to wait for a reply's first sound before the listener's own voice says it
READ = "Read the user's text aloud, word for word, in the language it is in. Add nothing, and don't answer it."


class Session:
    """One connection, kept open: it costs nothing idle, and saves the connecting on the next turn. Audio goes up only
    from the wake word to the end of a request and through a listening window, even a silent one; replies leave the
    conversation out, so no old audio is billed."""

    def __init__(self, key: str) -> None:
        self.key, self.ws, self.audio = key, None, queue.Queue()
        self.text = None  # the last request's words, once finished
        self.stopped_at = self.sent_at = 0.0
        self.words_ms = None  # how long the words took after the end of speech

    def open(self) -> bool:
        """True once connected; a failure only goes to the log, and the next turn tries again."""
        if self.ws:
            return True
        try:
            from websockets.sync.client import connect

            model = os.environ.get("OPENAI_REALTIME_MODEL") or MODEL
            self.ws = connect(URL.format(model=model), additional_headers={"Authorization": f"Bearer {self.key}"},
                              open_timeout=3, max_size=None)
            self.send(type="session.update", session={
                "type": "realtime", "output_modalities": ["audio"],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": RATE},
                        "transcription": {"model": "gpt-transcribe", "prompt": listener.VOCAB},
                        # low: it lets the user take their time. Only ending the turn here: the router decides the reply.
                        "turn_detection": {"type": "semantic_vad", "eagerness": "low",
                                           "create_response": False, "interrupt_response": False},
                    },
                    "output": {"format": {"type": "audio/pcm", "rate": RATE},
                               "voice": os.environ.get("OPENAI_VOICE") or "marin"},
                },
            })
            threading.Thread(target=self.receive, args=(self.ws,), daemon=True).start()
            return True
        except Exception as e:
            self.ws = None
            listener.emit("status", text=f"Realtime won't connect: {e}")
            return False

    def send(self, **event) -> None:
        self.ws.send(json.dumps(event))

    def feed(self, chunk: np.ndarray) -> None:
        """A mic chunk, from the listener's 16 kHz to 24 kHz."""
        at = np.arange(len(chunk) * RATE // listener.RATE) * listener.RATE / RATE
        up = np.interp(at, np.arange(len(chunk)), chunk).astype(np.int16)
        try:
            self.send(type="input_audio_buffer.append", audio=base64.b64encode(up.tobytes()).decode())
        except Exception:  # the listener's own end of speech still ends the request
            self.ws = None

    def clear(self) -> None:
        self.text = None
        try:
            self.send(type="input_audio_buffer.clear")
        except Exception:
            self.ws = None

    def read_aloud(self, text: str) -> None:
        while not self.audio.empty():
            self.audio.get()
        self.sent_at = time.monotonic()
        self.send(type="response.create", response={
            "conversation": "none", "output_modalities": ["audio"], "instructions": READ,
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}]})

    def receive(self, ws) -> None:
        try:
            for message in ws:
                event = json.loads(message)
                kind = event.get("type", "")
                if kind == "input_audio_buffer.speech_stopped":
                    self.stopped_at = time.monotonic()
                elif kind == "conversation.item.input_audio_transcription.delta":
                    listener.emit("partial", text=listener.strip_wake(event.get("delta", "")))
                elif kind == "conversation.item.input_audio_transcription.completed":
                    if self.stopped_at:
                        self.words_ms = ms(self.stopped_at)
                        listener.emit("status", text=f"Realtime: words {self.words_ms} ms after the end of speech")
                    self.text = event.get("transcript", "").strip()
                elif kind == "response.output_audio.delta":
                    self.audio.put(base64.b64decode(event["delta"]))
                elif kind == "response.done":
                    self.audio.put(None)
                elif kind in ("error", "conversation.item.input_audio_transcription.failed"):
                    listener.emit("status", text=f"Realtime: {json.dumps(event.get('error'))}")
                    self.audio.put(None)
        except Exception as e:
            listener.emit("status", text=f"Realtime closed: {e}")
        if self.ws is ws:
            self.ws = None
        self.audio.put(None)


def ms(since: float) -> int:
    return round((time.monotonic() - since) * 1000)


class NoLive:
    """Stands in for the listener's live words: the session's own go to the window."""
    feed = stop = lambda *a: None


told = None  # the words the session heard for the clip being handed over, instead of transcribe()
plain_transcribe = listener.transcribe


def transcribe(clip: np.ndarray) -> str:
    global told
    if told is None:
        return plain_transcribe(clip)
    text, told = told, None
    listener.heard_how = {"engine": "openai"}
    return text


class RealtimeEars(listener.Ears):
    streaming = False
    session: Session = None

    def __init__(self) -> None:
        self.session = Session(os.environ["OPENAI_API_KEY"])
        super().__init__()

    def record(self, on_done, start=(), give_up: int = listener.GIVE_UP) -> None:
        super().record(on_done, start, give_up)
        self.streaming = on_done != self.take_done and self.session.open()  # voice training stays local
        if self.streaming:
            self.session.clear()
            self.live = NoLive()
            for chunk in start:
                self.session.feed(chunk)

    def record_chunk(self, chunk: np.ndarray) -> None:
        global told
        if self.streaming:
            self.session.feed(chunk)
            said = self.session.text
            if said is not None:
                self.session.text = None
                # "Hey Jarvis" alone, then a pause, ends a turn too: the request is still to come.
                if listener.strip_wake(said):
                    self.streaming, told = False, said
                    self.stop_live()
                    self.on_done(np.concatenate(self.clip + [chunk]))
                    return
        super().record_chunk(chunk)

    def wait_for_wake(self, keep: bool = False) -> None:
        self.streaming = False
        super().wait_for_wake(keep)

    def play(self, samples, rate, tail: float = listener.ECHO, drain: bool = True) -> bool:
        if told is not None and samples is listener.CHIME_DOWN[0]:
            return True  # the "heard you" sound takes half a second, and the answer is about to start
        return super().play(samples, rate, tail, drain)

    def say(self, text: str, asked: bool = True, hold: bool = False, window: bool = True) -> None:
        """As Ears.say, but the sound plays as it arrives. A call's heads-up and any failure before the first sound go
        to Ears.say."""
        import sounddevice as sd

        call = self.busy()
        if (call and hold) or not self.session.open():
            return super().say(text, asked, hold, window)
        listen = bool(self.followup) and asked and window and not call
        try:  # any failure goes to Ears.say, which sends the notification for a line that needs one
            self.session.read_aloud(text)
            sound = self.session.audio.get(timeout=FIRST_SOUND)
        except Exception as e:
            sound = None
            listener.emit("status", text=f"Realtime voice failed: {e}")
        if sound is None:
            return super().say(text, asked, hold, window)
        listener.emit("status", text=f"Realtime: first sound {ms(self.session.sent_at)} ms after the text")
        if hold and listen:
            listener.emit("caption", text=text, remind=True)
        listener.emit("said", text=text)
        self.hush()
        problem = listener.output_problem()
        if problem:
            listener.emit("caption", text=f"{problem} I said: {text}")
        try:
            with sd.RawOutputStream(samplerate=RATE, channels=1, dtype="int16") as out:
                while sound is not None:
                    out.write(sound)
                    sound = self.session.audio.get(timeout=30)
                out.write(bytes(int(RATE * listener.DRAIN) * 2))
        except Exception as e:  # no speaker, or the sound stopped coming: what it said is in the log and the window
            listener.emit("error", message=f"Can't play: {e}")
            if not problem:
                listener.emit("caption", text=f"I can't play sound. {listener.CANT_HEAR} I said: {text}")
        self.deaf_until = time.monotonic() + listener.ECHO
        listener.emit("spoken", listening=listen)
        if listen:
            self.play(*listener.CHIME_UP, tail=0.15)
            self.record(lambda clip: self.request_done(clip) if clip is not None else self.close(), give_up=self.followup)
        else:
            self.wait_for_wake(keep=not asked and bool(self.reply_by))


def measure(path: str) -> None:
    """Sends a clip at the speed it was spoken, then has one line read aloud, and prints the timings. Plays nothing."""
    import soundfile as sf

    data, rate = sf.read(path, dtype="int16", always_2d=True)
    assert rate == listener.RATE, f"{path} must be {listener.RATE} Hz"
    s = Session(os.environ["OPENAI_API_KEY"])
    start = time.monotonic()
    assert s.open(), "no connection"
    print(f"connected in {ms(start)} ms")
    clip = data[:, 0]
    for i in range(0, len(clip), listener.CHUNK):
        s.feed(clip[i:i + listener.CHUNK])
        time.sleep(listener.CHUNK / listener.RATE)
    for _ in range(int(listener.END_QUIET)):  # the quiet after a request, at the speed of the mic
        s.feed(np.zeros(listener.CHUNK, np.int16))
        time.sleep(listener.CHUNK / listener.RATE)
        if s.text is not None:
            break
    print(f"heard: {s.text!r}")
    print(f"words after the end of speech: {s.words_ms} ms")
    s.read_aloud("Sige, on it.")
    first = s.audio.get(timeout=10)
    print(f"first sound after the text: {ms(s.sent_at)} ms" if first else "no sound")


if __name__ == "__main__":
    listener.load_env()
    key = os.environ.get("OPENAI_API_KEY")
    if len(sys.argv) > 2 and sys.argv[1] == "measure":
        measure(sys.argv[2]) if key else print("OPENAI_API_KEY is missing")
    else:
        if key:
            listener.Ears = RealtimeEars
            listener.transcribe = transcribe
        listener.main([])
