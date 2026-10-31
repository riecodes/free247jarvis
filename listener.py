"""The ears and voice of the boss: waits for "Hey Jarvis", answers "Jarvis here", records the request that follows, turns it into text, and speaks the boss's replies.

voice.mjs (the channel server) starts this and talks to it over pipes. It reads one command per stdin line
and writes one JSON event per stdout line:

  commands  on | off | enroll | cancel | listen (record without the wake word) | quit
            looking                             the user is checking that it's there: show why they may not hear it
            say <text>                          answers a request just heard: said in full, then the follow-up window
            end <text>                          as say, but it closes the exchange: no follow-up window
            late <text>                         an older reply, or a question nobody prompted: a heads-up in a call, else as say
            tell <text>                         news nobody asked for: a heads-up in a call, else in full; no follow-up window
  events    status {text}                       a model is loading or downloading
            state {on, trained}                 after on, off, enroll and cancel
            caption {text, looking}             show this on screen; looking: voice.mjs adds what the user is waiting on
            queued {text}                       the user has the floor: said once they are done
            peak {word, score, level}           how high a try at the wake word scored, fired or not, and how loud (RMS)
            wake                                heard the wake word, now recording the request
            heard {text}                        the request as text
            nothing                             woke up, but no request followed
            said {wav}                          a reply was spoken (and saved to wav)
            held {text}                         a call is on: not said, kept by voice.mjs until the user asks for it
            enroll {prompt, done, total, retry} voice training: what to say next
            enrolled                            voice training finished
            error {message}

Everything but speech to text runs on the CPU: openWakeWord (its own hey_jarvis, plus a verifier trained on the
user's voice, once trained), Silero VAD to hear when a request ends, and Kokoro 82M for
the voice. Speech to text is Groq's whisper-large-v3-turbo, which handles Tagalog and Taglish.

With VOICE_ENGINE=elevenlabs and an ElevenLabs key, speech to text is ElevenLabs Scribe v2 and the voice is an
ElevenLabs voice (your own clone, or a stock one). If ElevenLabs fails (no credits, no internet), it falls back
to Groq and Kokoro for that request.

Run `python listener.py train` once to train the verifier on your voice, `python listener.py fetch` to
download the models ahead of time.
"""
import asyncio
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
# The wake word: the model in models/, and what it says on waking (in the current voice, from a clip cached in tmp/).
# Only this one: gdiamos/hey-claude scored 0.99 with nobody saying it (2026-10-30), and the user dropped it.
WAKES = {
    "hey_jarvis": ("hey_jarvis_v0.1", "Jarvis here."),  # openWakeWord's official model
}
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
# Tuning knobs. WAKE_THRESHOLD (default 0.5) is read from .env in Ears; lower it when it misses a real "Hey Jarvis".
SPEECH = 0.5  # Silero VAD score that counts as speech
# Counted in 80 ms chunks.
PRE_ROLL = 3  # chunks from just before the wake fired, so "Hey Jarvis, tell..." said in one breath keeps its start
GRACE = 5  # speech within this many chunks of the wake is one breath ("Hey Jarvis, status"): no "Jarvis here"
MIN_VOICED = 3  # less speech than this is a click or a cough, not a request
END_QUIET = 62  # about 5s of quiet ends a request (1s cut people off mid-sentence, 2s still cut thinking pauses)
ECHO = 1.0  # seconds the mic stays deaf after a reply: the room's echo, and a moment before the next "Hey Jarvis"
SILENT_WARN = 30  # seconds of pure zeros from the mic before it says the mic seems off
HEADS_UP_GAP = 300  # seconds between heads-ups in one call; lines in between are only held
PEAK_FLOOR = 0.03  # wake word scores from here up count as a try: its peak goes to the log, to tune WAKE_THRESHOLD by
NEAR_MISS = 0.12  # a peak from here up to the threshold gets the near-miss tick
CUE_GAP = 2  # seconds between near-miss ticks
LOOK_TRIES, LOOK_WINDOW = 2, 20  # this many tries that got nowhere within this many seconds: they are looking for it
CANT_HEAR = "Can't hear me? Check your speaker's power and knob, your headphones, and your PC's sound."
SPOKE_WAIT = 3  # a line waits until the user has been quiet this many seconds, even outside a recording
HOLD_MAX = 30  # but no longer than this outside a recording: speech that long is a TV or someone else
REPLY_HOLD = 60  # seconds a request keeps the video paused while no reply comes, under rules.mjs's FRESH
ORCH_WINDOW = r"\b(PC|LP) Orchestrator$"  # the orch's terminal title, from ccorchname in the cc profile
SWP_KEEP = 0x13  # SetWindowPos: SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
# Silence after each sound. sd.wait() closes the stream when the last buffer is queued, and on this MME speaker
# that is about 0.28 s before it has played: measured on the endpoint's peak meter, the 0.28 s "heard" tone lost
# its last 0.12 s and more. Without this the end of every sound and reply is cut.
DRAIN = 0.35
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
# A try at the wake word that got no pop: almost heard you, say it again. One faint high tick, synthesized, pitched
# above the three above (all 1030 Hz or lower). sounds/local/near.wav overrides it.
CHIME_NEAR = earcon("near", chime(2200, note=0.045, level=0.1))


def emit(event: str, **data) -> None:
    EVENTS.write(json.dumps({"event": event, **data}) + "\n")
    EVENTS.flush()


def in_call() -> bool:
    """Another app is capturing from a microphone: a call, a meeting, a stream. Asks WASAPI for its live capture
    sessions, because Windows' privacy registry goes stale (here its last mic entry was 2026-09-17, with Voicemod and
    this listener on the mic right then). CALL_IGNORE in .env names apps that hold the mic all day. A meeting with
    the mic muted may release it, and then this can't tell."""
    try:
        import comtypes
        import psutil
        from pycaw.constants import CLSID_MMDeviceEnumerator, DEVICE_STATE, EDataFlow
        from pycaw.pycaw import IAudioSessionControl2, IAudioSessionManager2, IMMDeviceEnumerator

        ignore = [w.strip().lower() for w in (os.environ.get("CALL_IGNORE") or "voicemod").split(",") if w.strip()]
        enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
        devices = enum.EnumAudioEndpoints(EDataFlow.eCapture.value, DEVICE_STATE.ACTIVE.value)
        for d in range(devices.GetCount()):
            manager = devices.Item(d).Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None)
            sessions = manager.QueryInterface(IAudioSessionManager2).GetSessionEnumerator()
            for s in range(sessions.GetCount()):
                session = sessions.GetSession(s).QueryInterface(IAudioSessionControl2)
                pid = session.GetProcessId()
                if session.GetState() != 1 or pid in (0, os.getpid()):  # 1: active
                    continue
                try:
                    name = psutil.Process(pid).name().lower()
                except psutil.Error:  # it just ended
                    continue
                if not any(w in name for w in ignore):
                    return True
    except Exception as e:  # can't tell: speak as if there is no call
        emit("error", message=f"Can't check for a call: {e}")
    return False


def output_problem() -> str:
    """Why the user can't hear a line, when Windows can tell; empty when it can't (a speaker switched off at its
    knob looks like any other). PortAudio keeps the output it found at start, so a new Windows default is not used."""
    try:
        import sounddevice as sd
        from pycaw.pycaw import AudioUtilities

        try:
            device = AudioUtilities.GetSpeakers()
            name = device.FriendlyName
        except Exception:
            return "Windows has no speaker right now: plug one in or turn it on."
        volume = device.EndpointVolume
        if volume.GetMute():
            return "Your PC's sound is muted: unmute it to hear me."
        if volume.GetMasterVolumeLevelScalar() < 0.02:
            return "Your PC's volume is at zero: turn it up to hear me."
        mine = sd.query_devices(kind="output")["name"]
        if mine[:20] not in name:  # MME cuts names at 31 characters
            return f"Windows switched its sound to {name}, but I still play on {mine}: switch back, or restart me."
    except Exception as e:  # can't tell: the same as nothing wrong
        emit("error", message=f"Can't check the speaker: {e}")
    return ""


async def playing_sessions() -> list:
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status

    manager = await Manager.request_async()
    return [s for s in manager.get_sessions() if s.get_playback_info().playback_status == Status.PLAYING]


def media_playing() -> bool:
    try:
        return bool(asyncio.run(playing_sessions()))
    except Exception:
        return False


def pause_media() -> list:
    """Pauses whatever is playing in Windows' media sessions (browsers, Spotify) and returns just those, to resume."""
    async def pause() -> list:
        playing = await playing_sessions()
        for session in playing:
            await session.try_pause_async()
        return playing

    try:
        return asyncio.run(pause())
    except Exception as e:
        emit("error", message=f"Can't pause media: {e}")
        return []


def resume_media(sessions: list) -> None:
    async def resume() -> None:
        for session in sessions:
            await session.try_play_async()

    try:
        asyncio.run(resume())
    except Exception as e:  # such as a tab closed meanwhile
        emit("error", message=f"Can't resume media: {e}")


def orch_window() -> int:
    """The orch's terminal, 0 when there is none. Terminal windows only: a browser tab can carry that title too."""
    from ctypes import WINFUNCTYPE, create_unicode_buffer, windll, wintypes

    found = []

    def each(h, _):
        name = create_unicode_buffer(300)
        windll.user32.GetClassNameW(h, name, 300)
        if name.value == "CASCADIA_HOSTING_WINDOW_CLASS":
            windll.user32.GetWindowTextW(h, name, 300)
            if re.search(ORCH_WINDOW, name.value):
                found.append(h)
        return True

    windll.user32.EnumWindows(WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(each), 0)
    return found[0] if found else 0


def raise_orch() -> tuple[int, bool] | None:
    """Shows the orch's terminal above the other windows and leaves the keyboard where it is, so typing elsewhere never
    lands in the orch. Returns what lower_orch needs; None when there is no such window, or it is already in front."""
    try:
        from ctypes import windll
        from ctypes.wintypes import HWND

        user32 = windll.user32
        h = orch_window()
        if not h or user32.GetForegroundWindow() == h:
            return None
        minimized = bool(user32.IsIconic(h))
        if minimized:
            user32.ShowWindow(h, 4)  # SW_SHOWNOACTIVATE
        user32.SetWindowPos(h, HWND(-1), 0, 0, 0, 0, SWP_KEEP)  # topmost and back: the top of the normal windows
        user32.SetWindowPos(h, HWND(-2), 0, 0, 0, 0, SWP_KEEP)
        return h, minimized
    except Exception as e:
        emit("error", message=f"Can't show the orch's window: {e}")
        return None


def lower_orch(raised: tuple[int, bool]) -> None:
    """Puts it back: minimized if it was, else behind the window in front. Stays up if the user has clicked into it."""
    try:
        from ctypes import windll
        from ctypes.wintypes import HWND

        user32 = windll.user32
        h, minimized = raised
        front = user32.GetForegroundWindow()
        if front == h:
            return
        if minimized:
            user32.ShowWindow(h, 7)  # SW_SHOWMINNOACTIVE
        else:
            user32.SetWindowPos(h, HWND(front), 0, 0, 0, 0, SWP_KEEP)
    except Exception as e:
        emit("error", message=f"Can't put the orch's window back: {e}")


def load_env() -> None:
    """KEY=value lines from .env next to this file; real environment variables win."""
    env = HERE / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, eq, value = line.partition("=")
            if eq and not key.strip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


NAMES = r"(jarvis|jervis)"


def strip_wake(text: str) -> str:
    """The pre-roll carries the wake word into the transcript, and a "Hey Jarvis" said again mid-request is dropped
    too."""
    text = re.sub(rf"^\W*((hey|hi|hay|okay|ok)\W+)?{NAMES}\b\W*", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(rf"\b(hey|hi|hay|okay|ok)\W+{NAMES}\b\W*", "", text, flags=re.IGNORECASE).strip()


def wake_words() -> list[str]:
    return list(WAKES)


def verifier(word: str) -> Path:
    """The voice verifier trained for this wake word (`listener.py train`)."""
    return MODELS / f"my_voice_{word}.pkl"


def fetch() -> None:
    """Downloads every model on first use: about 120MB, mostly the Kokoro voice."""
    import requests
    from openwakeword.utils import download_models

    MODELS.mkdir(exist_ok=True)
    download_models(["hey_jarvis"], target_directory=str(MODELS))  # plus the feature and VAD models
    for name, url in [(n, KOKORO_URL + n) for n in KOKORO]:
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
                              # The clip can start mid wake word; without the keyterm Scribe mishears it.
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
        self.vad_boost = float(os.environ.get("VAD_BOOST") or 1)  # the wake word and speech to text cope without it
        self.tts = Kokoro.from_session(kokoro_session(), str(MODELS / KOKORO[1]))  # also the fallback for ElevenLabs
        emit("status", text="Voice: ElevenLabs" if el_key() else "Voice: Groq and Kokoro")
        emit("status", text=f"Kokoro on the {'GPU' if 'CUDA' in self.tts.sess.get_providers()[0] else 'CPU'}")
        self.acks = {WAKES[w][0]: self.load_ack(WAKES[w][1]) for w in self.words}  # by model name, as scores are
        self.deaf_until = 0.0  # audio recorded before this moment was our own voice coming out of the speaker
        self.recent: deque[np.ndarray] = deque(maxlen=PRE_ROLL)
        self.paused: list = []  # media sessions paused for an exchange, resumed when it is over
        self.raised: tuple[int, bool] | None = None  # the orch's window, shown because that paused something
        self.reply_by = 0.0  # a request was heard: the video stays paused for its reply until this moment
        self.next_heads_up = 0.0  # no heads-up before this moment
        self.voiced = 0  # chunks of speech in the clip being recorded
        self.peak, self.peak_word, self.peak_level = 0.0, "", 0  # the highest wake word score of the try going on
        self.next_cue = 0.0  # no near-miss tick before this moment
        self.queue: list[tuple[str, dict]] = []  # lines waiting for the user to finish, oldest first
        self.queue_since = 0.0  # when the oldest of them started waiting
        self.last_speech = 0.0  # when the VAD last heard speech
        self.tries: list[float] = []  # recent tries at the wake word that got nowhere
        self.wait_for_wake()

    def feed(self, chunk: np.ndarray) -> None:
        self.on_chunk(chunk)

    def hush(self) -> None:
        """Pauses what is playing, and if that stopped something, shows the orch's window. See release."""
        playing = pause_media()
        self.paused += playing
        if playing and not self.raised:
            self.raised = raise_orch()

    def release(self) -> None:
        """The exchange is over: the window back, then the video. Only what hush paused resumes, so a video the user
        paused stays paused."""
        self.reply_by = 0.0
        if self.raised:
            lower_orch(self.raised)
            self.raised = None
        if self.paused:
            resume_media(self.paused)
            self.paused = []

    def wait_for_wake(self, keep: bool = False) -> None:
        if not keep:  # not earlier: a video's sound in the follow-up window would be recorded as a request
            self.release()
        self.oww.reset()
        self.recent.clear()
        self.peak = 0.0
        self.on_chunk = self.wake_chunk

    def is_speech(self, chunk: np.ndarray) -> bool:
        """Silero stops hearing a quiet mic long before the wake word or Whisper do, so far-away speech ended as "nobody
        spoke". Only its copy of the chunk is boosted."""
        louder = np.clip(chunk.astype(np.float64) * self.vad_boost, -32768, 32767).astype(np.int16)
        return self.vad.predict(louder, frame_size=640) >= SPEECH  # about 0.6 ms per chunk

    def wake_chunk(self, chunk: np.ndarray) -> None:
        if self.is_speech(chunk):
            self.last_speech = time.monotonic()
        self.recent.append(chunk)
        scores = self.oww.predict(chunk)
        fired = max(scores, key=scores.get)
        score = float(scores[fired])
        if score >= PEAK_FLOOR:
            self.peak_level = max(self.peak_level, int(np.sqrt(np.mean(chunk.astype(np.float64) ** 2))))
        if score >= self.threshold:
            emit("peak", word=fired, score=round(score, 2), level=self.peak_level)
            self.peak_level = 0
            emit("wake")  # also while the boss works on the last request: this one reaches it as a new message
            self.hush()  # first, so the video's sound stays out of the request            # Heard the wake word: short and undrained, so little of a one-breath request is lost. Its blip is at the
            # start of a longer file, so the stream closing early doesn't reach it.
            self.play(*CHIME_UP, tail=0.05, drain=False)
            self.record(self.request_done, list(self.recent))
            self.ack, self.grace, self.on_chunk = self.acks[fired], GRACE, self.after_wake
        elif score >= PEAK_FLOOR:
            if score > self.peak:
                self.peak, self.peak_word = score, fired
        elif self.peak:  # the try is over: only now is its peak known
            peak, self.peak = self.peak, 0.0
            emit("peak", word=self.peak_word, score=round(peak, 2), level=self.peak_level)
            self.peak_level = 0
            if peak >= NEAR_MISS:
                self.cue(CHIME_NEAR)
                self.tried(stray=True)

    def tried(self, stray: bool = False) -> None:
        """A try at the wake word got nowhere. Repeated, the user is looking for it and may not hear its sounds. A
        near miss could be a video or the other side of a call (stray), so those two keep it quiet."""
        now = time.monotonic()
        self.tries = [t for t in self.tries if now - t < LOOK_WINDOW] + [now]
        if len(self.tries) >= LOOK_TRIES:
            self.tries = []
            if not (stray and (in_call() or media_playing())):
                emit("caption", text=self.looking(), looking=True)

    def looking(self) -> str:
        return f"Hello, I'm Jarvis, and I can hear you. {output_problem() or CANT_HEAR}"

    def cue(self, sound: tuple[np.ndarray, int]) -> None:
        """A sound that answers a try at the wake word: at most one per CUE_GAP, and none in a call."""
        if time.monotonic() >= self.next_cue and not in_call():
            self.next_cue = time.monotonic() + CUE_GAP
            self.play(*sound, tail=0.05)

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
        if self.is_speech(chunk):
            self.voiced, self.quiet = self.voiced + 1, 0
            self.last_speech = time.monotonic()
        else:
            self.quiet += 1
        spoke = self.voiced >= MIN_VOICED
        if (spoke and self.quiet >= END_QUIET) or (not spoke and len(self.clip) >= self.give_up) or len(self.clip) >= MAX_CLIP:
            self.on_done(np.concatenate(self.clip) if spoke else None)

    def request_done(self, clip: np.ndarray | None) -> None:
        self.play(*(CHIME_DOWN if clip is not None else CHIME_CLOSE), tail=0.1)  # heard you, or stopped listening
        self.wait_for_wake(keep=clip is not None)  # first, so a failed transcription still leaves the ears listening
        text = strip_wake(transcribe(clip)) if clip is not None else ""
        words = re.findall(r"\w+", text.lower())
        if set(words) <= set(re.findall(r"\w+", VOCAB.lower())) or " ".join(words) in HALLUCINATIONS:
            text = ""  # nothing, Whisper's prompt handed back, or what Whisper says for noise
        if text:
            self.tries = []
            self.reply_by = time.monotonic() + REPLY_HOLD
            emit("heard", text=text)
        else:
            self.release()  # a false wake: the video is back at once
            emit("nothing")
            self.tried()  # such as "Jarvis, Jarvis", which leaves no words once the wake word is taken out

    def close(self) -> None:
        """The follow-up window ran out with nothing said: the done sound, then back to the wake word."""
        self.play(*CHIME_CLOSE, tail=0.1)
        self.wait_for_wake()

    def user_turn(self) -> bool:
        """The user has the floor: a recording or a follow-up window is on, or they spoke a moment ago."""
        if self.on_chunk != self.wake_chunk:
            return True
        now = time.monotonic()
        return now - self.last_speech < SPOKE_WAIT and now - self.queue_since < HOLD_MAX

    def line(self, text: str, **how) -> None:
        """Every spoken line comes through here, so it never talks over the user. See flush."""
        if not self.queue:
            self.queue_since = time.monotonic()
        self.queue.append((text, how))
        if self.user_turn():
            emit("queued", text=text)

    def flush(self) -> None:
        """Says the oldest waiting line once the user is done. The main loop calls this after every event."""
        if self.queue and not self.user_turn():
            text, how = self.queue.pop(0)
            try:
                self.say(text, **how)
            except Exception as e:
                emit("error", message=f"Can't speak: {e}")
                emit("caption", text=f"My voice failed, so in words: {text}")
        elif self.reply_by and not self.queue and time.monotonic() >= self.reply_by and self.on_chunk == self.wake_chunk:
            self.release()  # no reply came: the boss is on something long, and its reply pauses the video again

    def say(self, text: str, asked: bool = True, hold: bool = False, window: bool = True) -> None:
        """Speaks a line with Kokoro, media paused, and keeps a copy in tmp/reply.wav. The caller mutes the mic
        meanwhile. Only a line that wants an answer (asked and window) opens the follow-up window, and never in a call,
        so call audio is not sent to speech to text. With hold, a call gets a short heads-up and the line goes back
        as `held`."""
        import soundfile as sf

        call = in_call()
        if call and hold:
            emit("held", text=text)
            if time.monotonic() < self.next_heads_up:
                return
            self.next_heads_up = time.monotonic() + HEADS_UP_GAP
            title = (os.environ.get("VOICE_TITLE") or "").strip()
            text = f"{title}, I have an update." if title else "I have an update."
        listen = bool(self.followup) and asked and window and not call
        samples, rate, _ = self.speech(text)
        REPLY_WAV.parent.mkdir(exist_ok=True)
        sf.write(REPLY_WAV.with_suffix(".partial.wav"), samples, rate)
        os.replace(REPLY_WAV.with_suffix(".partial.wav"), REPLY_WAV)
        emit("said", wav=str(REPLY_WAV), text=text)
        if listen and rate == CHIME_UP[1]:  # the chime in the same stream, the instant the words end
            samples = np.concatenate([samples.astype(np.float32), np.zeros(rate * 6 // 10, np.float32), CHIME_UP[0]])  # 0.7 s after the last word
        self.hush()
        problem = output_problem()  # not caught by the sound failing: a muted speaker plays along silently
        if problem:
            emit("caption", text=f"{problem} I said: {text}")
        if not self.play(samples, rate) and not problem:
            emit("caption", text=f"I can't play sound. {CANT_HEAR} I said: {text}")
        if listen:  # the user may answer without the wake word for a few seconds, then it waits for it again
            if rate != CHIME_UP[1]:
                self.play(*CHIME_UP, tail=0.15)  # the mic is open again
            self.record(lambda clip: self.request_done(clip) if clip is not None else self.close(),
                        give_up=self.followup)
        else:
            self.wait_for_wake(keep=not asked and bool(self.reply_by))  # news meanwhile: the reply is still to come

    def play(self, samples: np.ndarray, rate: int, tail: float = ECHO, drain: bool = True) -> bool:
        """Plays it with the mic deaf until `tail` seconds after the end. False if it could not play."""
        played = True
        try:
            import sounddevice as sd

            sd.play(np.concatenate([samples, np.zeros(int(rate * DRAIN), samples.dtype)]) if drain else samples, rate)
            sd.wait()
        except Exception as e:  # no speaker: a reply's wav is still there
            emit("error", message=f"Can't play: {e}")
            played = False
        self.deaf_until = time.monotonic() + tail
        return played

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


def mic_device(want: str | None = None):
    """The first input whose name contains `want` (MIC_DEVICE from .env, such as "WebCamera"), else Windows' default."""
    import sounddevice as sd

    want = (os.environ.get("MIC_DEVICE") if want is None else want or "") or ""
    return next((i for i, d in enumerate(sd.query_devices()) if want and d["max_input_channels"] > 0
                 and want.lower() in d["name"].lower()), None)


def open_mic(events: queue.Queue, want: str | None = None):
    """Opens `want` (MIC_DEVICE by default), else MIC_FALLBACK, else Windows' default, and says when it had to move on.
    MIC_DEVICE can match an input that won't open at 16 kHz (Voicemod's WDM-KS entry when its app is closed)."""
    import sounddevice as sd

    def open_on(device):
        stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK, device=device,
                                callback=lambda data, *_: events.put(("audio", data[:, 0].copy(), time.monotonic())))
        stream.start()
        return stream

    spare = os.environ.get("MIC_FALLBACK") or ""
    first = mic_device(want)
    failure = None
    for device, name in {first: want or "MIC_DEVICE", mic_device(spare): spare, None: "Windows' default microphone"}.items():
        try:
            stream = open_on(device)
        except Exception as e:
            emit("status", text=f"{name} won't open ({e})")
            failure = e
            continue
        if device != first:
            emit("status", text=f"Using {name}")
        return stream
    raise failure


def spare_mic(mic, events: queue.Queue):
    """The mic went silent: moves to MIC_FALLBACK and returns the new stream, or None with the old one left as it was."""
    spare = os.environ.get("MIC_FALLBACK") or ""
    if not spare:
        return None
    try:
        new = open_mic(events, spare)
    except Exception as e:
        emit("error", message=f"Can't open {spare}: {e}")
        return None
    mic.close()
    return new


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
    # ponytail: on the spare until the mic is turned off and on or the voice restarts; no check for the first one's return.
    on_spare = False
    while True:
        ears.flush()
        kind, value, at = events.get()
        if kind == "audio":
            if value.any():
                zeros_since, warned = 0.0, False
            elif not zeros_since:
                zeros_since = at
            elif not warned and at - zeros_since > SILENT_WARN:
                name = os.environ.get("MIC_FALLBACK" if on_spare else "MIC_DEVICE", "")
                if mic is not None and not on_spare and (new := spare_mic(mic, events)):
                    mic, on_spare, zeros_since = new, True, 0.0
                    spare = os.environ["MIC_FALLBACK"]
                    emit("status", text=f"{name or 'The microphone'} sent pure silence for {SILENT_WARN} s; now on {spare}")
                    ears.line(f"The {name} microphone went silent, so I switched to {spare}.", asked=False, hold=True)
                    continue
                warned = True
                emit("error", message=f"The microphone ({name or 'Windows default'}) sends pure silence: is it on?")
                emit("caption", text=f"The {name} microphone sends nothing, so I can't hear you. Check that "
                                     f"{name} is running." if name else "The microphone sends nothing, so I can't hear "
                                     "you. Check that it's plugged in and not muted.")
                ears.line(f"The {name} microphone hears nothing at all. Check that {name} is running." if name
                          else "The microphone hears nothing at all. Check that it's plugged in and not muted.",
                          asked=False, hold=True)
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
        if value == "looking":
            emit("caption", text=ears.looking(), looking=True)
            continue
        if value == "listen":  # after "Say that again?": record the next sentence without the wake word
            if not ears.queue and not in_call():
                ears.record(ears.request_done)
            continue
        if value.startswith(("say ", "end ", "late ", "tell ")):
            verb, text = value.split(" ", 1)
            # With the mic closed no window can open or end, and paused media would never resume.
            ears.line(text, asked=verb != "tell" and mic is not None, hold=verb in ("late", "tell"), window=verb != "end")
            continue
        if value in ("on", "off"):
            zeros_since, warned = 0.0, False  # time with the mic closed is not silence
        if value in ("on", "enroll") and mic is None:
            try:
                mic, on_spare = open_mic(events), False
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
