"""A trial, opt-in: Gemini Live hears the end of a request and answers small talk itself, in its own voice, about a second
after the last word. Everything else it hands over (its ask_orch tool), and the request goes on as it does today: the
clip to Groq for its words (Gemini's own transcript of Taglish is poor), then the router and the orch. The wake word stays
local, and nothing reaches Google before it. Replies from the router and the orch are still spoken by Kokoro.

Run instead of listener.py with VOICE_LISTENER=gemini.py and GEMINI_API_KEY in .env (a free key from
aistudio.google.com/apikey; on the free tier Google may use what is sent to improve its products). Without the key it is
listener.py. When the connection, a turn or the sound fails, the listener's own end of speech takes over, as it always
runs alongside: whichever ends the request first wins. GEMINI_LIVE_MODEL and GEMINI_VOICE change the model and the voice.
"""
import base64
import json
import os
import queue
import threading
import time

import numpy as np

import listener

URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
MODEL = "gemini-3.8-live"  # NON_BLOCKING tools; 3.1 Flash Live doesn't have them
RATE = 24000  # its voice
# Small talk only (2026-11-13, tried on the user's kept requests): told to answer "general questions" too, it said
# "Alexandros Liner operates daily trips from Ternate to MOA" about his own app's data, and "No response needed" aloud.
SYSTEM = ("You are Jarvis, the voice in front of the user's Claude Code orchestrator. You answer only small talk yourself: a "
          "greeting, thanks, how are you, the time or date, or a joke, in one short plain-English sentence that says {title} once. "
          "Everything else, in any language, goes to the orchestrator: call ask_orch with the user's words and say nothing at all, "
          "not even an acknowledgment. That includes any question of fact, anything about their apps, work, sessions or you, and "
          "anything you are unsure of. Never answer a question of fact yourself. The audio may start with your own short "
          "greeting (\"Yes, {title}\", \"I'm listening\"): never answer that, wait for the user.")
ASK_ORCH = {"name": "ask_orch", "description": "Hand the user's request to the orchestrator, which answers it.",
            "parameters": {"type": "OBJECT", "properties": {"request": {"type": "STRING"}}, "required": ["request"]},
            "behavior": "NON_BLOCKING"}
SETUP_WAIT = 3  # seconds for the connection and setup; the listener's own path runs meanwhile
SILENCE_MS = 1500  # quiet that ends a turn for Gemini (GEMINI_SILENCE_MS)
# Gemini's hand-over counts only when Smart Turn also hears the request finished (GEMINI_GATE); else the listener goes
# on. On 20 of the user's requests with long pauses, the 5 cut short scored 0.01 to 0.34; 8 of the 15 others pass.
GATE = 0.35


def ms(since: float) -> int:
    return round((time.monotonic() - since) * 1000)


class Live:
    """One Live session per recording: opened in the background, so the mic never waits; chunks before it's ready are
    kept and sent once it is. Its events go to `events`: ("audio", bytes), ("call", None), ("done", None), ("failed",
    reason); what it heard and said build up in `heard` and `said`."""

    def __init__(self, key: str) -> None:
        self.key, self.ws, self.events, self.waiting, self.lock = key, None, queue.Queue(), [], threading.Lock()
        self.heard, self.said, self.closed = "", "", False
        threading.Thread(target=self.open, daemon=True).start()

    def open(self) -> None:
        try:
            from websockets.sync.client import connect

            ws = connect(URL, additional_headers={"x-goog-api-key": self.key}, open_timeout=SETUP_WAIT, max_size=None)
            title = (os.environ.get("VOICE_TITLE") or "sir").strip().lower()
            ws.send(json.dumps({"setup": {
                "model": f"models/{os.environ.get('GEMINI_LIVE_MODEL') or MODEL}",
                "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": os.environ.get("GEMINI_VOICE") or "Puck"}}}},
                "systemInstruction": {"parts": [{"text": SYSTEM.format(title=title)}]},
                "tools": [{"functionDeclarations": [ASK_ORCH]}],
                "realtimeInputConfig": {"automaticActivityDetection": {
                    "endOfSpeechSensitivity": "END_SENSITIVITY_LOW", "silenceDurationMs": int(os.environ.get("GEMINI_SILENCE_MS") or SILENCE_MS)}},
                "inputAudioTranscription": {}, "outputAudioTranscription": {}}}))
            if "setupComplete" not in json.loads(ws.recv(timeout=SETUP_WAIT)):
                raise RuntimeError("no setupComplete")
            with self.lock:
                if self.closed:
                    return ws.close()
                self.ws = ws
                for chunk in self.waiting:
                    self.send(chunk)
                self.waiting = []
            for message in ws:
                self.on(json.loads(message))
        except Exception as e:
            if not self.closed:
                self.events.put(("failed", str(e)))
        self.events.put(("done", None))

    def on(self, m: dict) -> None:
        sc = m.get("serverContent", {})
        self.heard += sc.get("inputTranscription", {}).get("text", "")
        if said := sc.get("outputTranscription", {}).get("text", ""):
            self.said += said
        for part in sc.get("modelTurn", {}).get("parts", []):
            if "inlineData" in part:
                self.events.put(("audio", base64.b64decode(part["inlineData"]["data"])))
        if "toolCall" in m:
            self.events.put(("call", None))
        if sc.get("turnComplete"):
            self.events.put(("done", None))

    def send(self, chunk: np.ndarray) -> None:
        self.ws.send(json.dumps({"realtimeInput": {"audio": {"data": base64.b64encode(chunk.astype(np.int16).tobytes()).decode(),
                                                            "mimeType": f"audio/pcm;rate={listener.RATE}"}}}))

    def feed(self, chunk: np.ndarray) -> None:
        with self.lock:
            if self.closed:
                return
            if not self.ws:
                self.waiting.append(chunk)
                return
            try:
                self.send(chunk)
            except Exception as e:
                self.closed = True
                self.events.put(("failed", str(e)))

    def close(self) -> None:
        with self.lock:
            self.closed = True
            ws, self.ws = self.ws, None
        if ws:
            try:
                ws.close()
            except Exception:
                pass


class GeminiEars(listener.Ears):
    gemini: Live = None

    def record(self, on_done, start=(), give_up: int = listener.GIVE_UP) -> None:
        self.close_gemini()
        super().record(on_done, start, give_up)
        if on_done != self.take_done:  # voice training stays local; the wake word itself (start) isn't sent
            self.gemini = Live(os.environ["GEMINI_API_KEY"])

    def close_gemini(self) -> None:
        if self.gemini:
            self.gemini.close()
            self.gemini = None

    def wait_for_wake(self, keep: bool = False) -> None:
        self.close_gemini()  # the request ended, whichever way: a late answer from Gemini is dropped
        super().wait_for_wake(keep)

    def record_chunk(self, chunk: np.ndarray) -> None:
        g = self.gemini
        if g:
            g.feed(chunk)
            while not g.events.empty():
                kind, value = g.events.get()
                if kind == "failed":
                    listener.emit("status", text=f"Gemini Live failed, the listener goes on: {value}")
                    self.close_gemini()
                    break
                if kind == "call" and not self.finished():
                    continue
                if kind == "call":  # not small talk: the clip goes on as any request, to Groq and the router
                    listener.emit("status", text=f"Gemini: handed over {ms(self.last_speech)} ms after the last word")
                    self.close_gemini()
                    self.stop_live()
                    self.ended = (time.monotonic(), self.quiet)
                    return self.on_done(np.concatenate(self.clip + [chunk]))
                if kind == "audio":  # its own answer
                    return self.answer(g, value)
        super().record_chunk(chunk)

    def finished(self) -> bool:
        """Smart Turn agrees the request is over; without it, or when it fails, Gemini decides."""
        if not self.turn:
            return True
        try:
            done = float(self.turn.run(None, {"input_features": listener.turn_features(np.concatenate(self.clip[-100:]))})[0].ravel()[0])
        except Exception:
            return True
        if done >= float(os.environ.get("GEMINI_GATE") or GATE):
            return True
        listener.emit("status", text=f"Gemini handed over, but it sounds unfinished ({done:.2f}): the listener goes on")
        return False

    def answer(self, g: Live, first: bytes) -> None:
        """Gemini answers small talk itself: its sound as it arrives, then the wake word, or the window if it asked."""
        import sounddevice as sd

        listener.emit("status", text=f"Gemini: first sound {ms(self.last_speech)} ms after the last word")
        self.gemini = None
        self.stop_live()
        self.hush()
        sound = first
        try:
            with sd.RawOutputStream(samplerate=RATE, channels=1, dtype="int16") as out:
                while sound:
                    out.write(sound)
                    kind, sound = g.events.get(timeout=10)
                    if kind != "audio":
                        break
                out.write(bytes(int(RATE * listener.DRAIN) * 2))
        except Exception as e:
            listener.emit("error", message=f"Can't play Gemini's answer: {e}")
        g.close()
        heard, said = g.heard.strip(), g.said.strip()
        listener.emit("status", text=f"Gemini answered it itself: {heard!r}")
        listener.emit("said", text=said)
        self.said, self.words_end, self.deaf_until = said, time.monotonic(), time.monotonic() + listener.ECHO
        listen = said.endswith("?") and bool(self.followup)
        listener.emit("spoken", listening=listen)
        if listen:
            self.play(*listener.CHIME_UP, tail=0.15)
            self.record(lambda clip: self.request_done(clip) if clip is not None else self.close(), give_up=self.followup)
        else:
            self.wait_for_wake()


if __name__ == "__main__":
    listener.load_env()
    if os.environ.get("GEMINI_API_KEY"):
        listener.Ears = GeminiEars
    listener.main([])
