"""The ears and voice of the boss: waits for "Hey Jarvis" (or "Hey Claude", WAKE_WORDS in .env), answers
"Jarvis here", records the request that follows, turns it into text, and speaks the boss's replies.

voice.mjs (the channel server) starts this and talks to it over pipes. It reads one command per stdin line
and writes one JSON event per stdout line:

  commands  on | off | enroll | cancel | say <text> | listen (record without the wake word) | quit
  events    status {text}                       a model is loading or downloading
            state {on, trained}                 after on, off, enroll and cancel
            wake                                heard the wake word, now recording the request
            heard {text}                        the request as text; no new wake until a reply is said
            nothing                             woke up, but no request followed
            said {wav}                          a reply was spoken (and saved to wav)
            enroll {prompt, done, total, retry} voice training: what to say next
            enrolled                            voice training finished
            error {message}

Everything but speech to text runs on the CPU: openWakeWord (its own hey_jarvis, or gdiamos/hey-claude, plus a
verifier trained on the user's voice, once trained), Silero VAD to hear when a request ends, and Kokoro 82M for
the voice. Speech to text is Groq's whisper-large-v3-turbo, which handles Tagalog and Taglish.

With VOICE_ENGINE=elevenlabs and an ElevenLabs key, speech to text is ElevenLabs Scribe v2 and the voice is an
ElevenLabs voice (your own clone, or a stock one). If ElevenLabs fails (no credits, no internet), it falls back
to Groq and Kokoro for that request.

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
# WAKE_WORDS in .env (comma separated) picks from these, hey_jarvis by default: the model in models/, and what
# it says on waking (in the current voice, from a clip cached in tmp/).
WAKES = {
    "hey_jarvis": ("hey_jarvis_v0.1", "Jarvis here."),  # openWakeWord's official model
    "hey_claude": ("hey_claude", "Claude here."),  # gdiamos/hey-claude
}
WAKE_URL = "https://huggingface.co/gdiamos/hey-claude/resolve/main/hey_claude.onnx"
# Words Whisper should spell right. Never a whole sentence: on a near-silent clip Whisper hands its prompt back,
# and a command in it ("Tell terminal 3 to fix the navbar") was then acted on.
VOCAB = "Claude, Jarvis, terminal, session, Notepad, Taglish, pakisabi, yung."
FEATURES = {
    "inference_framework": "onnx",
    "melspec_model_path": str(MODELS / "melspectrogram.onnx"),
    "embedding_model_path": str(MODELS / "embedding_model.onnx"),
}
KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
# The full-precision model: on a GTX 1650 about 0.6 s for a short reply, and on the CPU about 2 s, where the int8
# one took 4 to 6 s (int8 math is slow on the CPU and not run on the GPU).
KOKORO = ["kokoro-v1.0.onnx", "voices-v1.0.bin"]
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
EL_URL = "https://api.elevenlabs.io/v1"
EL_VOICE = "JBFqnCBsd6RMkjVDRZzb"  # George, a stock British ElevenLabs voice, when ELEVENLABS_VOICE_ID is empty

RATE = 16000
CHUNK = 1280  # 80 ms, the frame openWakeWord expects
# Tuning knobs. WAKE_THRESHOLD (default 0.5) is read from .env in Ears; the model card suggests 0.3 when it
# misses a real "hey Claude".
SPEECH = 0.5  # Silero VAD score that counts as speech
# Counted in 80 ms chunks.
PRE_ROLL = 3  # chunks from just before the wake fired, so "Hey Claude, tell..." said in one breath keeps its start
GRACE = 5  # speech within this many chunks of the wake is one breath ("Hey Jarvis, status"): no "Jarvis here"
MIN_VOICED = 3  # less speech than this is a click or a cough, not a request
END_QUIET = 62  # about 5s of quiet ends a request (1s cut people off mid-sentence, 2s still cut thinking pauses)
REPLY_WAIT = 45  # seconds a heard request may wait for its spoken reply; no new wake meanwhile
ECHO = 1.0  # seconds the mic stays deaf after a reply: the room's echo, and a moment before the next "Hey Jarvis"
SILENT_WARN = 30  # seconds of pure zeros from the mic before it says the mic seems off
# Whisper's confidence per stretch of speech; below it, the stretch is dropped. Groq leaves no_speech_prob at 0, and
# its "Thank you." for pure noise scores like real speech (avg_logprob about -0.5, clean speech -0.1 to -0.5), so
# this only drops what Whisper is very unsure of; HALLUCINATIONS catches the rest.
MIN_LOGPROB = -1.0
# What Whisper says for noise or silence. Dropping a real "thank you" costs nothing: there is nothing to do.
HALLUCINATIONS = {"thank you", "thanks", "thanks for watching", "thank you for watching", "you", "bye"}
GIVE_UP = 62  # about 5s without speech after waking: nobody is talking
MAX_CLIP = 22500  # 30 min cap on one request; past 10 min it goes as Opus (WAV tops Groq's free 25 MB at 13 min)

WAKE_TAKES = 5  # then these sentences
SENTENCES = [
    "Now read this aloud: “Tell terminal two to run the tests and fix whatever fails.”",
    "And this: “Pakibuksan mo yung notepad tapos i-type mo hello.”",
    "Last one: “The quick brown fox jumps over the lazy dog by the river.”",
]


def chime(*freqs: float, note: float = 0.07, rate: int = 24000, level: float = 0.16) -> tuple[np.ndarray, int]:
    """A short soft sine chime, one note per frequency, with fades so it never clicks."""
    t = np.arange(int(note * rate)) / rate
    env = np.minimum(1, np.minimum(t, note - t) / 0.012)  # 12 ms fade in and out
    return np.concatenate([np.sin(2 * np.pi * f * t) * env * level for f in freqs]).astype(np.float32), rate


def earcon(name: str, fallback: tuple[np.ndarray, int]) -> tuple[np.ndarray, int]:
    """sounds/<name>.wav (Kenney Interface Sounds, CC0, see sounds/LICENSE.txt), or the synthesized chime, at the
    voices' 24 kHz so it can ride on the end of a reply. A tenth of a second of silence leads it: a speaker that
    wakes up for a new stream swallows the start, and a 0.15 s blip went missing whole (2026-10-28)."""
    rate = 24000
    try:
        import soundfile as sf

        own = HERE / "sounds" / "local" / f"{name}.wav"  # your own pick, gitignored, wins over the shipped one
        samples, src = sf.read(own if own.is_file() else HERE / "sounds" / f"{name}.wav", dtype="float32")
        samples = samples.mean(axis=1) if samples.ndim > 1 else samples  # full volume: the pack peaks at 0.9
        n = round(len(samples) * rate / src)
        samples = np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples)
    except Exception:
        samples, rate = fallback
    return np.concatenate([np.zeros(rate // 10), samples]).astype(np.float32), rate


# Earcons instead of words: listen = I'm listening (the wake word, or after a reply), heard = got it, working on it.
CHIME_UP = earcon("listen", chime(660, 990))
CHIME_DOWN = earcon("heard", chime(990, 660))
CHIME_CLOSE = earcon("close", chime(660, 440))  # done listening, nothing heard (Kenney switch_002 at the pop's level)


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


NAMES = r"(claude|claud|cloud|clyde|clod|jarvis|jervis)"


def strip_wake(text: str) -> str:
    """The pre-roll carries the wake word into the transcript, sometimes misheard as Cloud or Clyde, and a "Hey
    Jarvis" said again mid-request is dropped too."""
    text = re.sub(rf"^\W*((hey|hi|hay|okay|ok)\W+)?{NAMES}\b\W*", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(rf"\b(hey|hi|hay|okay|ok)\W+{NAMES}\b\W*", "", text, flags=re.IGNORECASE).strip()


def wake_words() -> list[str]:
    """WAKE_WORDS from .env, such as "hey_claude" or "hey_jarvis,hey_claude"; hey_jarvis when empty."""
    words = [w.strip().lower() for w in (os.environ.get("WAKE_WORDS") or "").split(",")]
    return [w for w in words if w in WAKES] or ["hey_jarvis"]


def verifier(word: str) -> Path:
    """The voice verifier trained for this wake word (`listener.py train`)."""
    return MODELS / f"my_voice_{word}.pkl"


def fetch() -> None:
    """Downloads every model on first use: about 120MB, mostly the Kokoro voice."""
    import requests
    from openwakeword.utils import download_models

    MODELS.mkdir(exist_ok=True)
    download_models(["hey_jarvis"], target_directory=str(MODELS))  # plus the feature and VAD models
    for name, url in [("hey_claude.onnx", WAKE_URL)] + [(n, KOKORO_URL + n) for n in KOKORO]:
        path = MODELS / name
        if not path.is_file():
            emit("status", text=f"Downloading {name}...")
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            path.with_suffix(".partial").write_bytes(r.content)
            os.replace(path.with_suffix(".partial"), path)


def wake_model(words: list[str], verify: bool = True):
    """These wake words, each with its voice verifier once trained (voice training judges takes without one).
    Its scores are keyed by model name, WAKES[word][0]."""
    import openwakeword

    return openwakeword.Model(
        wakeword_models=[str(MODELS / f"{WAKES[w][0]}.onnx") for w in words],
        custom_verifier_models={WAKES[w][0]: str(verifier(w)) for w in words if verify and verifier(w).is_file()},
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


def audio_file(clip: np.ndarray) -> tuple[str, bytes, str]:
    """The clip to upload: WAV, or Opus (about 6 MB for 30 min) once it runs past 10 min."""
    if len(clip) <= RATE * 600:
        return "request.wav", wav_bytes(clip), "audio/wav"
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, clip.astype(np.int16), RATE, format="OGG", subtype="OPUS")
    return "request.ogg", buf.getvalue(), "audio/ogg"


def el_key() -> str:
    """The ElevenLabs key when VOICE_ENGINE=elevenlabs: ELEVENLABS_API_KEY, or the file ELEVENLABS_API_KEY_FILE names."""
    if os.environ.get("VOICE_ENGINE", "").lower() != "elevenlabs":
        return ""
    key, path = os.environ.get("ELEVENLABS_API_KEY", ""), os.environ.get("ELEVENLABS_API_KEY_FILE", "")
    if not key and path and Path(path).is_file():
        key = Path(path).read_text(encoding="utf-8").strip()
    return key


def voice_key() -> str:
    """The voice that speaks: elevenlabs_<voice ID> when ElevenLabs is set up, else kokoro_<Kokoro voice> (see
    voices-v1.0.bin). Read at call time, not at import: .env is loaded after this module."""
    if el_key():
        return "elevenlabs_" + (os.environ.get("ELEVENLABS_VOICE_ID") or EL_VOICE)
    return "kokoro_" + (os.environ.get("VOICE") or "bm_george")


def transcribe(clip: np.ndarray) -> str:
    """ElevenLabs Scribe v2 when set up, else (or when it fails) Groq. Both detect English, Tagalog and Taglish."""
    import requests

    if key := el_key():
        try:
            r = requests.post(f"{EL_URL}/speech-to-text", headers={"xi-api-key": key},
                              files={"file": audio_file(clip)},
                              # The clip starts mid "Claude"; without the keyterm Scribe hears "Odd" or "God".
                              data={"model_id": "scribe_v2", "tag_audio_events": "false",
                                    "keyterms": [w.replace("_", " ").title() for w in wake_words()]},
                              timeout=600)
            r.raise_for_status()
            return r.json()["text"].strip()
        except Exception as e:
            emit("error", message=f"ElevenLabs speech to text failed, trying Groq: {e}")
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise RuntimeError("GROQ_API_KEY is missing: put it in .env (free at https://console.groq.com/keys)")
    r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"},
                      files={"file": audio_file(clip)},
                      data={"model": "whisper-large-v3-turbo", "response_format": "verbose_json", "prompt": VOCAB},
                      timeout=600)
    r.raise_for_status()
    return " ".join(s["text"].strip() for s in r.json().get("segments", []) if s["avg_logprob"] > MIN_LOGPROB).strip()


class Ears:
    """Turns 80 ms microphone chunks into events: waits for the wake word, then records until the speaker stops."""

    def __init__(self) -> None:
        from kokoro_onnx import Kokoro
        from openwakeword.vad import VAD

        emit("status", text="Loading the wake word and the voice...")
        fetch()
        self.words = wake_words()
        self.oww = wake_model(self.words)
        self.threshold = float(os.environ.get("WAKE_THRESHOLD") or 0.5)  # here, not at import: .env loads later
        self.followup = round(float(os.environ.get("FOLLOWUP_SECONDS") or 8) / 0.08)  # in chunks; 0: off
        self.vad = VAD(str(MODELS / "silero_vad.onnx"))
        self.tts = Kokoro.from_session(kokoro_session(), str(MODELS / KOKORO[1]))  # also the fallback for ElevenLabs
        emit("status", text="Voice: ElevenLabs" if el_key() else "Voice: Groq and Kokoro")
        emit("status", text=f"Kokoro on the {'GPU' if 'CUDA' in self.tts.sess.get_providers()[0] else 'CPU'}")
        self.acks = {WAKES[w][0]: self.load_ack(WAKES[w][1]) for w in self.words}  # by model name, as scores are
        self.deaf_until = 0.0  # audio recorded before this moment was our own voice coming out of the speaker
        self.busy_until = 0.0  # a heard request waits for its reply until then: no new wake
        self.recent: deque[np.ndarray] = deque(maxlen=PRE_ROLL)
        self.wait_for_wake()

    def feed(self, chunk: np.ndarray) -> None:
        self.on_chunk(chunk)

    def wait_for_wake(self) -> None:
        self.oww.reset()
        self.recent.clear()
        self.on_chunk = self.wake_chunk

    def wake_chunk(self, chunk: np.ndarray) -> None:
        if time.monotonic() < self.busy_until:  # saying "Hey Jarvis" again before the reply must not reopen it
            return
        self.recent.append(chunk)
        scores = self.oww.predict(chunk)
        fired = max(scores, key=scores.get)
        if scores[fired] >= self.threshold:
            emit("wake")
            self.play(*CHIME_UP, tail=0.05)  # heard the wake word: short, so little of a one-breath request is lost
            self.record(self.request_done, list(self.recent))
            self.ack, self.grace, self.on_chunk = self.acks[fired], GRACE, self.after_wake

    def after_wake(self, chunk: np.ndarray) -> None:
        """Still talking right after the wake word: keep recording. A pause: say "Jarvis here" (the mic is deaf
        meanwhile, so it can't hear or wake itself), then record what follows."""
        self.record_chunk(chunk)
        self.grace -= 1
        if self.voiced:
            self.on_chunk = self.record_chunk
        elif not self.grace:
            self.record(self.request_done)  # the wake chime already played (it replaced the spoken "Jarvis here")

    def record(self, on_done, start=(), give_up: int = GIVE_UP) -> None:
        """Collects chunks until the speaker stops, then calls on_done with the clip, or with None if nobody spoke
        within give_up chunks."""
        self.vad.reset_states()
        self.clip, self.voiced, self.quiet, self.on_done, self.give_up = list(start), 0, 0, on_done, give_up
        self.on_chunk = self.record_chunk

    def record_chunk(self, chunk: np.ndarray) -> None:
        self.clip.append(chunk)
        if self.vad.predict(chunk, frame_size=640) >= SPEECH:
            self.voiced, self.quiet = self.voiced + 1, 0
        else:
            self.quiet += 1
        spoke = self.voiced >= MIN_VOICED
        if (spoke and self.quiet >= END_QUIET) or (not spoke and len(self.clip) >= self.give_up) or len(self.clip) >= MAX_CLIP:
            self.on_done(np.concatenate(self.clip) if spoke else None)

    def request_done(self, clip: np.ndarray | None) -> None:
        self.play(*(CHIME_DOWN if clip is not None else CHIME_CLOSE), tail=0.1)  # heard you, or stopped listening
        self.wait_for_wake()  # first, so a failed transcription still leaves the ears listening
        text = strip_wake(transcribe(clip)) if clip is not None else ""
        words = re.findall(r"\w+", text.lower())
        if set(words) <= set(re.findall(r"\w+", VOCAB.lower())) or " ".join(words) in HALLUCINATIONS:
            text = ""  # nothing, Whisper's prompt handed back, or what Whisper says for noise
        if text:
            emit("heard", text=text)
            self.busy_until = time.monotonic() + REPLY_WAIT
        else:
            emit("nothing")

    def close(self) -> None:
        """The follow-up window ran out with nothing said: the done sound, then back to the wake word."""
        self.play(*CHIME_CLOSE, tail=0.1)
        self.wait_for_wake()

    def say(self, text: str) -> None:
        """Speaks a reply with Kokoro and keeps a copy in tmp/reply.wav. The caller mutes the mic meanwhile."""
        import soundfile as sf

        samples, rate, _ = self.speech(text)
        REPLY_WAV.parent.mkdir(exist_ok=True)
        sf.write(REPLY_WAV.with_suffix(".partial.wav"), samples, rate)
        os.replace(REPLY_WAV.with_suffix(".partial.wav"), REPLY_WAV)
        emit("said", wav=str(REPLY_WAV), text=text)
        if self.followup and rate == CHIME_UP[1]:  # the chime in the same stream, the instant the words end
            samples = np.concatenate([samples.astype(np.float32), np.zeros(rate * 6 // 10, np.float32), CHIME_UP[0]])  # 0.7 s after the last word
        self.play(samples, rate)
        self.busy_until = 0.0  # replied: the next "Hey Jarvis" works once the echo is gone
        if self.followup:  # the user may answer without the wake word for a few seconds, then it waits for it again
            if rate != CHIME_UP[1]:
                self.play(*CHIME_UP, tail=0.15)  # the mic is open again
            self.record(lambda clip: self.request_done(clip) if clip is not None else self.close(),
                        give_up=self.followup)
        else:
            self.wait_for_wake()

    def play(self, samples: np.ndarray, rate: int, tail: float = ECHO) -> None:
        """Plays it with the mic deaf until `tail` seconds after the end."""
        try:
            import sounddevice as sd

            sd.play(samples, rate)
            sd.wait()
        except Exception as e:  # no speaker: a reply's wav is still there
            emit("error", message=f"Can't play: {e}")
        self.deaf_until = time.monotonic() + tail

    def load_ack(self, text: str) -> tuple[np.ndarray, int]:
        """`text` in the current voice, rendered once per voice and cached in tmp/, so it plays the moment it's needed."""
        import soundfile as sf

        name = re.sub(r"\W", "", text.lower())
        path = HERE / "tmp" / f"{name}_{voice_key()}.wav"
        if not path.is_file():
            samples, rate, used = self.speech(text)
            path = HERE / "tmp" / f"{name}_{used}.wav"  # Kokoro's when ElevenLabs failed; it is tried again next start
            path.parent.mkdir(exist_ok=True)
            sf.write(path, samples, rate)
        return sf.read(path, dtype="float32")

    def speech(self, text: str) -> tuple[np.ndarray, int, str]:
        """The reply as audio, plus the voice_key() that said it: the ElevenLabs voice when set up, else (or when it
        fails) Kokoro."""
        engine, _, voice = voice_key().partition("_")
        if engine == "elevenlabs":
            import requests

            try:
                r = requests.post(f"{EL_URL}/text-to-speech/{voice}",
                                  params={"output_format": "pcm_24000"}, headers={"xi-api-key": el_key()}, timeout=30,
                                  json={"text": text, "model_id": os.environ.get("ELEVENLABS_MODEL") or "eleven_flash_v2_5"})
                r.raise_for_status()
                return np.frombuffer(r.content, np.int16).astype(np.float32) / 32768, 24000, f"elevenlabs_{voice}"
            except Exception as e:
                emit("error", message=f"ElevenLabs voice failed, using Kokoro: {e}")
            voice = os.environ.get("VOICE") or "bm_george"
        # bm_/bf_ voices are British, so en-gb.
        samples, rate = self.tts.create(text, voice=voice, speed=1.0, lang="en-gb" if voice[0] == "b" else "en-us")
        return samples, rate, f"kokoro_{voice}"

    # Voice training: five takes of the first wake word and three sentences of other speech teach openWakeWord's
    # verifier how this user sounds, which cuts false wakes from other voices and the TV.

    def enroll(self) -> None:
        self.base = wake_model(self.words[:1], verify=False)  # the takes are judged by the plain model, as training does
        self.takes: list[np.ndarray] = []
        self.next_take()

    def next_take(self, retry: str = "") -> None:
        n, total = len(self.takes), WAKE_TAKES + len(SENTENCES)
        if n == total:
            return self.train()
        prompt = f"Say “{self.words[0].replace('_', ' ').title()}”" if n < WAKE_TAKES else SENTENCES[n - WAKE_TAKES]
        emit("enroll", prompt=prompt, done=n, total=total, retry=retry)
        self.record(self.take_done)

    def take_done(self, clip: np.ndarray | None) -> None:
        if clip is None:
            return self.next_take("I didn't hear anything. Try again.")
        if len(self.takes) < WAKE_TAKES and not self.has_wake(clip):
            return self.next_take("That didn't sound like the wake word. Try again.")
        self.takes.append(clip)
        self.next_take()

    def has_wake(self, clip: np.ndarray) -> bool:
        self.base.reset()
        audio = np.concatenate([np.zeros(RATE, np.int16), clip])  # a reset model ignores its first frames
        scores = [max(self.base.predict(audio[i:i + CHUNK]).values()) for i in range(0, len(audio) - CHUNK + 1, CHUNK)]
        return max(scores) >= self.threshold

    def train(self) -> None:
        import openwakeword

        total = WAKE_TAKES + len(SENTENCES)
        emit("enroll", prompt="Learning your voice...", done=total, total=total, retry="")
        word = self.words[0]
        with tempfile.TemporaryDirectory() as folder:  # the recordings are deleted once the verifier is trained
            paths = []
            for i, clip in enumerate(self.takes):
                paths.append(str(Path(folder) / f"{i}.wav"))
                Path(paths[-1]).write_bytes(wav_bytes(clip))
            partial = verifier(word).with_suffix(".partial")
            openwakeword.train_custom_verifier(paths[:WAKE_TAKES], paths[WAKE_TAKES:], str(partial),
                                               str(MODELS / f"{WAKES[word][0]}.onnx"), **FEATURES)
        os.replace(partial, verifier(word))
        self.oww = wake_model(self.words)
        emit("enrolled")
        self.wait_for_wake()


def kokoro_session():
    """Kokoro on the NVIDIA GPU when onnxruntime-gpu (setup.ps1 installs it when it finds one), the CUDA toolkit and
    cuDNN are installed, else on the CPU. CUDA_PATH comes from the CUDA installer; cuDNN from its default folder."""
    import onnxruntime as rt

    providers = ["CPUExecutionProvider"]
    if "CUDAExecutionProvider" in rt.get_available_providers() and (cuda := os.environ.get("CUDA_PATH")):
        version = re.sub(r"^v", "", Path(cuda).name)  # v13.0
        for d in [Path(cuda) / "bin" / "x64", Path(cuda) / "bin", *Path(r"C:\Program Files\NVIDIA\CUDNN").glob(f"v*/bin/{version}")]:
            if d.is_dir():
                os.add_dll_directory(str(d))
                os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"  # the CUDA provider loads its DLLs from PATH
        providers.insert(0, "CUDAExecutionProvider")
    return rt.InferenceSession(str(MODELS / KOKORO[0]), providers=providers)  # without CUDA it falls back to the CPU


def mic_device():
    """The first input whose name contains MIC_DEVICE from .env (such as "WebCamera"), else Windows' default."""
    import sounddevice as sd

    want = (os.environ.get("MIC_DEVICE") or "").lower()
    return next((i for i, d in enumerate(sd.query_devices()) if want and d["max_input_channels"] > 0
                 and want in d["name"].lower()), None)


def open_mic(events: queue.Queue):
    import sounddevice as sd

    stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK, device=mic_device(),
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
    # Nothing but exact zeros: a virtual mic whose app isn't running (Voicemod, which sends faint noise while it runs).
    zeros_since, warned = 0.0, False
    while True:
        kind, value, at = events.get()
        if kind == "audio":
            if value.any():
                zeros_since, warned = 0.0, False
            elif not zeros_since:
                zeros_since = at
            elif not warned and at - zeros_since > SILENT_WARN:
                warned, name = True, os.environ.get("MIC_DEVICE", "")
                emit("error", message=f"The microphone ({name or 'Windows default'}) sends pure silence: is it on?")
                try:
                    ears.say(f"The {name} microphone hears nothing at all. Check that {name} is running." if name
                             else "The microphone hears nothing at all. Check that it's plugged in and not muted.")
                except Exception as e:
                    emit("error", message=f"Can't speak: {e}")
                continue
            if mic is not None and at > ears.deaf_until:
                try:
                    ears.feed(value)
                except Exception as e:  # one failed request or training run must not stop the listening
                    emit("error", message=str(e))
                    ears.wait_for_wake()
            continue
        if value == "quit":
            break
        if value == "listen":  # after "Say that again?": record the next sentence without the wake word
            ears.record(ears.request_done)
            continue
        if value.startswith("say "):
            try:
                ears.say(value[4:])
            except Exception as e:
                emit("error", message=f"Can't speak: {e}")
            continue
        if value in ("on", "off"):
            zeros_since, warned = 0.0, False  # time with the mic closed is not silence
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
        emit("state", on=mic is not None, trained=verifier(ears.words[0]).is_file())
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
