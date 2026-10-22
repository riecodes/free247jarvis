"""The ears and voice of the boss: waits for "Hey Claude", records the request that follows, turns it into
text, and speaks the boss's replies.

voice.mjs (the channel server) starts this and talks to it over pipes. It reads one command per stdin line
and writes one JSON event per stdout line:

  commands  on | off | enroll | cancel | say <text> | quit
  events    status {text}                       a model is loading or downloading
            state {on, trained}                 after on, off, enroll and cancel
            wake                                heard the wake word, now recording the request
            heard {text}                        the request as text
            nothing                             woke up, but no request followed
            said {wav}                          a reply was spoken (and saved to wav)
            enroll {prompt, done, total, retry} voice training: what to say next
            enrolled                            voice training finished
            error {message}

Everything but speech to text runs on the CPU: openWakeWord with gdiamos/hey-claude (plus a verifier
trained on the user's voice, once trained), Silero VAD to hear when a request ends, and Kokoro 82M for the
voice. Speech to text is Groq's whisper-large-v3-turbo, which handles Tagalog and Taglish.

Run `python listener.py train` once to train the verifier on your voice, `python listener.py fetch` to
download the models ahead of time.
"""
import io
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
import wave
from collections import deque
from pathlib import Path

import numpy as np

EVENTS = sys.stdout
sys.stdout = sys.stderr  # libraries print progress; only events may reach the pipe

HERE = Path(__file__).resolve().parent
MODELS = HERE / "models"
REPLY_WAV = HERE / "tmp" / "reply.wav"
VERIFIER = MODELS / "my_voice.pkl"
WAKE = "hey_claude"
WAKE_URL = "https://huggingface.co/gdiamos/hey-claude/resolve/main/hey_claude.onnx"
FEATURES = {
    "inference_framework": "onnx",
    "melspec_model_path": str(MODELS / "melspectrogram.onnx"),
    "embedding_model_path": str(MODELS / "embedding_model.onnx"),
}
KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO = ["kokoro-v1.0.int8.onnx", "voices-v1.0.bin"]
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

RATE = 16000
CHUNK = 1280  # 80 ms, the frame openWakeWord expects
# Tuning knobs. The model card suggests 0.3 when it misses a real "hey Claude".
WAKE_THRESHOLD = float(os.environ.get("WAKE_THRESHOLD", "0.5"))
VOICE = os.environ.get("VOICE", "af_heart")  # Kokoro voice, see voices-v1.0.bin
SPEECH = 0.5  # Silero VAD score that counts as speech
# Counted in 80 ms chunks.
PRE_ROLL = 3  # chunks from just before the wake fired, so "Hey Claude, tell..." said in one breath keeps its start
MIN_VOICED = 3  # less speech than this is a click or a cough, not a request
END_QUIET = 12  # about 1s of quiet ends a request
GIVE_UP = 62  # about 5s without speech after waking: nobody is talking
MAX_CLIP = 375  # 30s cap on one request

WAKE_TAKES = 5
TAKES = ["Say “Hey Claude”"] * WAKE_TAKES + [
    "Now read this aloud: “Tell terminal two to run the tests and fix whatever fails.”",
    "And this: “Pakibuksan mo yung notepad tapos i-type mo hello.”",
    "Last one: “The quick brown fox jumps over the lazy dog by the river.”",
]


def emit(event: str, **data) -> None:
    EVENTS.write(json.dumps({"event": event, **data}) + "\n")
    EVENTS.flush()


def load_env() -> None:
    """KEY=value lines from .env next to this file; real environment variables win."""
    env = HERE / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, eq, value = line.partition("=")
            if eq and not key.strip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def strip_wake(text: str) -> str:
    """The pre-roll carries the wake word into the transcript, sometimes misheard as Cloud or Clyde."""
    return re.sub(r"^\W*((hey|hi|hay|okay|ok)\W+)?(claude|claud|cloud|clyde|clod)\b\W*", "", text.strip(),
                  flags=re.IGNORECASE)


def fetch() -> None:
    """Downloads every model on first use: about 120MB, mostly the Kokoro voice."""
    import requests
    from openwakeword.utils import download_models

    MODELS.mkdir(exist_ok=True)
    download_models([WAKE], target_directory=str(MODELS))  # only the feature and VAD models: hey_claude is not official
    for name, url in [(f"{WAKE}.onnx", WAKE_URL)] + [(n, KOKORO_URL + n) for n in KOKORO]:
        path = MODELS / name
        if not path.is_file():
            emit("status", text=f"Downloading {name}...")
            r = requests.get(url, timeout=600)
            r.raise_for_status()
            path.with_suffix(".partial").write_bytes(r.content)
            os.replace(path.with_suffix(".partial"), path)


def wake_model(verifier: Path | None = None):
    import openwakeword

    return openwakeword.Model(
        wakeword_models=[str(MODELS / f"{WAKE}.onnx")],
        custom_verifier_models={WAKE: str(verifier)} if verifier and verifier.is_file() else {},
        **FEATURES,
    )


def wav_bytes(clip: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(clip.astype(np.int16).tobytes())
    return buf.getvalue()


def transcribe(clip: np.ndarray) -> str:
    """Groq whisper-large-v3-turbo. Language is detected, so English, Tagalog and Taglish all work."""
    import requests

    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise RuntimeError("GROQ_API_KEY is missing: put it in .env (free at https://console.groq.com/keys)")
    r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"},
                      files={"file": ("request.wav", wav_bytes(clip), "audio/wav")},
                      data={"model": "whisper-large-v3-turbo", "response_format": "json",
                            "prompt": "Hey Claude, pakisabi kay terminal 2 na i-run yung tests. Tell terminal 3 to fix the navbar."}, timeout=60)
    r.raise_for_status()
    return r.json()["text"].strip()


class Ears:
    """Turns 80 ms microphone chunks into events: waits for the wake word, then records until the speaker stops."""

    def __init__(self) -> None:
        from kokoro_onnx import Kokoro
        from openwakeword.vad import VAD

        emit("status", text="Loading the wake word and the voice...")
        fetch()
        self.oww = wake_model(VERIFIER)
        self.vad = VAD(str(MODELS / "silero_vad.onnx"))
        self.tts = Kokoro(str(MODELS / KOKORO[0]), str(MODELS / KOKORO[1]))
        self.recent: deque[np.ndarray] = deque(maxlen=PRE_ROLL)
        self.wait_for_wake()

    def feed(self, chunk: np.ndarray) -> None:
        self.on_chunk(chunk)

    def wait_for_wake(self) -> None:
        self.oww.reset()
        self.recent.clear()
        self.on_chunk = self.wake_chunk

    def wake_chunk(self, chunk: np.ndarray) -> None:
        self.recent.append(chunk)
        if self.oww.predict(chunk)[WAKE] >= WAKE_THRESHOLD:
            emit("wake")
            beep()
            self.record(self.request_done, list(self.recent))

    def record(self, on_done, start=()) -> None:
        """Collects chunks until the speaker stops, then calls on_done with the clip, or with None if nobody spoke."""
        self.vad.reset_states()
        self.clip, self.voiced, self.quiet, self.on_done = list(start), 0, 0, on_done
        self.on_chunk = self.record_chunk

    def record_chunk(self, chunk: np.ndarray) -> None:
        self.clip.append(chunk)
        if self.vad.predict(chunk, frame_size=640) >= SPEECH:
            self.voiced, self.quiet = self.voiced + 1, 0
        else:
            self.quiet += 1
        spoke = self.voiced >= MIN_VOICED
        if (spoke and self.quiet >= END_QUIET) or (not spoke and len(self.clip) >= GIVE_UP) or len(self.clip) >= MAX_CLIP:
            self.on_done(np.concatenate(self.clip) if spoke else None)

    def request_done(self, clip: np.ndarray | None) -> None:
        self.wait_for_wake()  # first, so a failed transcription still leaves the ears listening
        text = strip_wake(transcribe(clip)) if clip is not None else ""
        if text:
            emit("heard", text=text)
        else:
            emit("nothing")

    def say(self, text: str) -> None:
        """Speaks a reply with Kokoro and keeps a copy in tmp/reply.wav. The caller mutes the mic meanwhile."""
        import soundfile as sf

        samples, rate = self.tts.create(text, voice=VOICE, speed=1.0, lang="en-us")
        REPLY_WAV.parent.mkdir(exist_ok=True)
        sf.write(REPLY_WAV.with_suffix(".partial.wav"), samples, rate)
        os.replace(REPLY_WAV.with_suffix(".partial.wav"), REPLY_WAV)
        emit("said", wav=str(REPLY_WAV), text=text)
        try:
            import sounddevice as sd

            sd.play(samples, rate)
            sd.wait()
        except Exception as e:  # no speaker: the wav is still there
            emit("error", message=f"Can't play the reply: {e}")
        self.wait_for_wake()

    # Voice training: five "Hey Claude" takes and three sentences of other speech teach openWakeWord's
    # verifier how this user sounds, which cuts false wakes from other voices and the TV.

    def enroll(self) -> None:
        self.base = wake_model()  # without a verifier: the takes are judged by the plain model, as training does
        self.takes: list[np.ndarray] = []
        self.next_take()

    def next_take(self, retry: str = "") -> None:
        n = len(self.takes)
        if n == len(TAKES):
            return self.train()
        emit("enroll", prompt=TAKES[n], done=n, total=len(TAKES), retry=retry)
        self.record(self.take_done)

    def take_done(self, clip: np.ndarray | None) -> None:
        if clip is None:
            return self.next_take("I didn't hear anything. Try again.")
        if len(self.takes) < WAKE_TAKES and not self.has_wake(clip):
            return self.next_take("That didn't sound like “Hey Claude”. Try again.")
        self.takes.append(clip)
        self.next_take()

    def has_wake(self, clip: np.ndarray) -> bool:
        self.base.reset()
        audio = np.concatenate([np.zeros(RATE, np.int16), clip])  # a reset model ignores its first frames
        scores = [self.base.predict(audio[i:i + CHUNK])[WAKE] for i in range(0, len(audio) - CHUNK + 1, CHUNK)]
        return max(scores) >= WAKE_THRESHOLD

    def train(self) -> None:
        import openwakeword

        emit("enroll", prompt="Learning your voice...", done=len(TAKES), total=len(TAKES), retry="")
        with tempfile.TemporaryDirectory() as folder:  # the recordings are deleted once the verifier is trained
            paths = []
            for i, clip in enumerate(self.takes):
                paths.append(str(Path(folder) / f"{i}.wav"))
                Path(paths[-1]).write_bytes(wav_bytes(clip))
            partial = VERIFIER.with_suffix(".partial")
            openwakeword.train_custom_verifier(paths[:WAKE_TAKES], paths[WAKE_TAKES:], str(partial),
                                               str(MODELS / f"{WAKE}.onnx"), **FEATURES)
        os.replace(partial, VERIFIER)
        self.oww = wake_model(VERIFIER)
        emit("enrolled")
        self.wait_for_wake()


def beep() -> None:
    """A short soft tone on wake, so the speaker knows it is listening. Too short and pure for the VAD to count."""
    try:
        import sounddevice as sd

        t = np.arange(int(0.12 * 24000)) / 24000
        sd.play((0.15 * np.sin(2 * np.pi * 880 * t) * np.hanning(len(t))).astype(np.float32), 24000)
    except Exception:
        pass


def open_mic(events: queue.Queue):
    import sounddevice as sd

    stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK,
                            callback=lambda data, *_: events.put(("audio", data[:, 0].copy(), time.monotonic())))
    stream.start()
    return stream


def main(commands: list[str]) -> None:
    load_env()
    events: queue.Queue = queue.Queue()  # microphone chunks and commands, in arrival order
    for c in commands:
        events.put(("command", c, 0))
    # A thread blocked reading stdin holds the C runtime's lock on it, and some DLLs (scipy's Fortran code)
    # touch stdin while they load, which then hangs the import forever. So commands come from a private copy
    # of the pipe, and stdin itself becomes NUL.
    pipe = open(os.dup(0), encoding="utf-8")
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)

    def read_commands() -> None:
        for line in pipe:
            events.put(("command", line.strip(), 0))
        events.put(("command", "quit", 0))  # the pipe closed: the boss has exited

    threading.Thread(target=read_commands, daemon=True).start()
    ears = Ears()
    mic = None
    deaf_until = 0.0  # audio recorded before this moment was the reply coming out of the speaker
    while True:
        kind, value, at = events.get()
        if kind == "audio":
            if mic is not None and at > deaf_until:
                try:
                    ears.feed(value)
                except Exception as e:  # one failed request or training run must not stop the listening
                    emit("error", message=str(e))
                    ears.wait_for_wake()
            continue
        if value == "quit":
            break
        if value.startswith("say "):
            try:
                ears.say(value[4:])
            except Exception as e:
                emit("error", message=f"Can't speak: {e}")
            deaf_until = time.monotonic() + 0.3  # the room's echo
            continue
        if value in ("on", "enroll") and mic is None:
            try:
                mic = open_mic(events)
            except Exception as e:  # no microphone, or Windows privacy settings block desktop apps
                emit("error", message=f"Can't open the microphone: {e}")
        elif value == "off" and mic is not None:
            mic.close()
            mic = None
        if value == "enroll" and mic is not None:
            ears.enroll()
        elif value in ("off", "cancel"):
            ears.wait_for_wake()
        emit("state", on=mic is not None, trained=VERIFIER.is_file())
    if mic is not None:
        mic.close()


def train() -> None:
    """`python listener.py train`: voice training at the console."""
    global emit

    def show(event: str, **data) -> None:
        if event == "enroll":
            print(f"[{data['done'] + 1}/{data['total']}] {data['retry']} {data['prompt']}".replace("  ", " "))
        elif event == "enrolled":
            print("Done. The boss now wakes on your voice (restart the boss to load it).")
            os._exit(0)
        elif event in ("status", "error"):
            print(data.get("text") or data.get("message"))

    emit = show
    main(["enroll"])


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "fetch":
        load_env()
        fetch()
    elif arg == "train":
        train()
    else:
        main([])
