"""The ears and voice of the boss: waits for "Hey Jarvis", answers "Jarvis here", records the request that follows, turns it into text, and speaks the boss's replies.

voice.mjs (the channel server) starts this and talks to it over pipes. It reads one command per stdin line
and writes one JSON event per stdout line:

  commands  on | off | enroll | cancel | listen (record without the wake word) | set NAME value | bank LINE | waiting JSON | quit
            watch on | watch off                the window opened or closed: live words only while it is open
            looking                             the user is checking that it's there: show why they may not hear it
            say <text>                          answers a request just heard: said in full, then the follow-up window
            end <text>                          as say, but it closes the exchange: no follow-up window
            late <text>                         an older reply, or a question nobody prompted: held while staying quiet, else as say
            tell <text>                         news nobody asked for: held while staying quiet, else in full; no follow-up window
  events    status {text}                       a model is loading or downloading
            state {on, trained}                 after on, off, enroll and cancel
            caption {text, looking, remind}     show this in the window; looking: voice.mjs adds what the user is waiting
                                                on and a notification; remind: a notification only
            queued {text}                       the user has the floor: said once they are done
            peak {word, score, level}           how high a try at the wake word scored, fired or not, and how loud (RMS)
            wake                                heard the wake word, now recording the request
            partial {text}                      live words of the request so far, for show only
            heard {text}                        the request as text
            nothing                             woke up, but no request followed
            cut_off {text}, lost {text}         back from a stop, or a request's words never came: a line for the boss to know too
            said {wav}                          a reply is about to play (saved to wav)
            spoken {listening}                  it has played; listening: the follow-up window is open
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
import base64
import difflib
import io
import json
import os
import queue
import random
import re
import sys
import tempfile
import threading
import time
import wave
import zlib
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
BASE_TERMS = ["Claude", "Jarvis", "terminal", "session", "Notepad", "Taglish", "pakisabi", "yung"]
PROMPT_MAX = 896  # Groq answers a longer prompt with a 400 (measured 2026-11-01): the request fails, nothing is cut


def load_terms(path: Path = HERE / "words.txt") -> list[str]:
    """BASE_TERMS, then one term per line of words.txt, up to what fits in the prompt; later lines drop first."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    unique: dict[str, str] = {}
    for term in BASE_TERMS + [line.split("#")[0].strip() for line in lines]:
        if term:
            unique.setdefault(term.lower(), term)
    terms: list[str] = []
    for term in unique.values():
        if len(", ".join(terms + [term])) + 1 > PROMPT_MAX:
            break
        terms.append(term)
    return terms


def load_fixes(path: Path = HERE / "words.txt") -> list[tuple[re.Pattern, str]]:
    """What a term is often heard as, from "Claude  # also: Clawed, Clawde" in words.txt. Explicit lists only: a guess at any
    close word turned "using" into "yung" on real requests."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    fixes = []
    for line in lines:
        if line.lstrip().startswith("#"):  # a comment, even one that shows the format
            continue
        term, _, also = line.partition("# also:")
        fixes += [(re.compile(rf"\b{re.escape(w.strip())}\b", re.IGNORECASE), term.strip())
                  for w in also.split(",") if w.strip() and term.strip()]
    return fixes


FIXES = load_fixes()


def fix_words(text: str) -> str:
    for wrong, right in FIXES:
        text = wrong.sub(right, text)
    return text


TERMS = load_terms()
VOCAB = ", ".join(TERMS) + "."
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
SCRIBE_LIVE_URL = ("wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v2_realtime"
                   "&audio_format=pcm_16000&commit_strategy=manual&keyterms=Hey%20Jarvis")

RATE = 16000
CHUNK = 1280  # 80 ms, the frame openWakeWord expects
# Tuning knobs. WAKE_THRESHOLD (default 0.5) is read from .env in Ears; lower it when it misses a real "Hey Jarvis".
SPEECH = 0.5  # Silero VAD score that counts as speech
# Counted in 80 ms chunks.
PRE_ROLL = 3  # chunks from just before the wake fired, so "Hey Jarvis, tell..." said in one breath keeps its start
NAME_ROLL = 19  # 1.5 s before the score fired: enough for speech to text to hear "Hey Jarvis" itself
NAME_TIMEOUT = 4  # seconds for that check; a real wake waits on it, typically 0.8 s, and its pop plays after
# Staying quiet: a call, or speech around while nobody woke it. TALK_SHARE and WAKE_STRICT are read from .env in Ears.
WAKE_STRICT = 0.7  # the wake word score needed then; tonight's real wakes went as low as 0.39, so not all the time
TALK_SHARE = 0.4  # this share of the last 30 s was speech: people are talking
TALK_CHUNKS, TALK_MIN = 375, 125  # 30 s, and no verdict on less than 10 s
QUIET_EVERY = 5  # seconds between checks for the window
SHORT_CLIP = 1125  # 90 s cap, thrown away unsent: a listening window or a quiet-time request. A real answer ran about 60 s.
GRACE = 5  # speech within this many chunks of the wake is one breath ("Hey Jarvis, status"): no "Jarvis here"
MIN_VOICED = 3  # less speech than this is a click or a cough, not a request
END_QUIET = 62  # about 5s of quiet ends a request (1s cut people off mid-sentence, 2s still cut thinking pauses)
ECHO = 1.0  # seconds the mic stays deaf after a sound, unless the caller says otherwise
# How long before a reply's last word the mic counts again (LISTEN_LEAD in .env; 0: at the last word, less: after it). Sound
# recorded while it speaks waits in the queue, so this keeps what the user said over the end, with no echo canceller. A
# USB mic with the speakers on: the reply stayed about at the room's noise, and the speech detector called 0-8% of it speech.
LISTEN_LEAD = 1.0
ECHO_ROOM = 0.3  # speech this long past the last word is the user's, not the speaker's or the room's
ECHO_WORDS = 12  # how far back from a reply's end its echo can reach into a clip
# Words at the end of a request that end it at once (CLOSING_CUT=off in .env turns it off). After CLOSING_GAP of quiet (.env)
# the words so far go to speech to text; silence stays the fallback for everything else.
CLOSING_GAP = 0.8
# Said on waking, with VOICE_TITLE after the comma. Rendered once per voice, in tmp/, so they play with no wait. Longer than
# GREETING_MAX and it's skipped: it would talk over the request. No closing phrase, no "Jarvis", and two words or more, so
# strip_echo can tell one when the mic hears it. After GREETING_AWAY of nothing, the time of day leads.
GREETINGS = ["Yes", "I'm here", "Right here", "Listening", "Go on", "I'm listening", "Here", "Tell me", "Yes, what is it",
             "Ready", "What's up", "Yes, I'm here", "With you", "Hello"]
GREETINGS_AT = {"Morning": range(4, 12), "Good day": range(12, 18), "Evening": (18, 19, 20, 21, 22, 23, 0, 1, 2, 3)}
GREETING_MAX, GREETING_AWAY, GREETING_SPEED = 1.0, 30 * 60, 1.2
REMIND_EVERY = 30 * 60  # seconds before the same waiting item can follow a greeting again
CLOSING_TAIL = 75  # chunks before the pause: 6 s, plenty for the words and quick to send
CLOSING_EVERY = 4  # seconds between checks, to stay under Groq's 20 requests a minute
CLOSING_TIMEOUT = 3
# After the start of the words or a clause: "how do I do it" and "where did it go" are no closing. A cut here costs a late
# word, sent as its own request. Whisper invents "Thank you" over long quiet, so only the words before the quiet go.
CLOSING = re.compile(r"(?:^|[.!?,]\s+)(?:(?:yeah|yes|okay|ok|so|then|please|just|and)\W+)*"
                     r"(?:do it|let's do it|go ahead|go for it|go|let's go|send it|thank you|thanks|that's it)\W*$", re.IGNORECASE)
SILENT_WARN = 30  # seconds of pure zeros from the mic before it says the mic seems off
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
# Free voice's live words, in chunks: every 4 s is 15 requests a minute, leaving room in Groq's 20 for the request itself.
LIVE_EVERY = 50
LIVE_SPARE, CLOSING_SPARE = 8, 4  # requests a minute kept free for wake checks and requests, when these two ask
LIVE_CLIP = 188  # the last 15 s
# What survives a stop, so it can say what it lost. Machine-local: tmp/ is neither in git nor synced.
EARS_STATE, EARS_WHY = HERE / "tmp" / "ears.json", HERE / "tmp" / "ears.why"
STATE_EVERY = 5  # seconds between saves, and at once when the state changes
CUT_RECENT = 300  # stopped longer ago than this: a fresh start, nothing to pick back up
HEARD_RECENT = 1800  # seconds "last I heard" stays worth saying
HEARD_WORDS = 12  # the end of it, which is where to pick up from: never a long read-out
LOST_GAP = 20  # seconds between "I lost that" lines: a window catching noise during a Groq limit must not loop on it
RESTART_QUIET = 60  # `listener.py restart` waits for this many seconds since the last speech
RESTART_WAIT = 30 * 60  # and gives up after this long
DATA_DAYS = 30  # voice data older than this is deleted
DATA_MAX = 2 * 1024 ** 3  # and past this many bytes of clips, the oldest go first

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


EMITTING = threading.Lock()  # live words come from their own threads


def emit(event: str, **data) -> None:
    with EMITTING:
        EVENTS.write(json.dumps({"event": event, **data}) + "\n")
        EVENTS.flush()


def in_call() -> bool:
    """A call, by what Windows can see; call_why says which signal. Next: speech around, in Ears.talking."""
    global call_why
    call_why = mic_holder() or call_window()
    return bool(call_why)


call_why = ""  # the signal behind the last in_call(), for the window
CALL_TITLES = {"Meet": r"^Meet\b", "Zoom": r"\bZoom (Meeting|Webinar)\b", "Teams": r"\b(Meeting|Call).*Microsoft Teams\b",
               "Webex": r"\bWebex (Meeting|Meetings)\b", "Messenger": r"\bMessenger call\b"}


def call_window() -> str:
    """A meeting's window title, for one that let go of a muted mic. Chrome's title is only its open tab's. Compared
    here, and never kept or sent: titles carry people's names."""
    from ctypes import WINFUNCTYPE, create_unicode_buffer, windll, wintypes

    found = []

    def each(h, _):
        if windll.user32.IsWindowVisible(h):
            title = create_unicode_buffer(300)
            windll.user32.GetWindowTextW(h, title, 300)
            found.extend(app for app, pattern in CALL_TITLES.items() if re.search(pattern, title.value))
        return True

    try:
        windll.user32.EnumWindows(WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(each), 0)
    except Exception as e:
        emit("error", message=f"Can't check for a meeting window: {e}")
    return f"a {found[0]} window" if found else ""


def mic_holder() -> str:
    """Another app capturing from a microphone: a call, a meeting, a stream; its name, or "". Asks WASAPI for its live
    capture sessions, because Windows' privacy registry goes stale (its last mic entry was 2026-09-17 during a Meet on
    2026-11-01). It can't tell which of Chrome's tabs. CALL_IGNORE in .env names apps that hold the mic all day."""
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
                    return f"{name.removesuffix('.exe')} on the mic"
    except Exception as e:  # can't tell: speak as if there is no call
        emit("error", message=f"Can't check for a call: {e}")
    return ""


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


def name_check(clip: np.ndarray) -> tuple[bool, str]:
    """The wake word model fires on sounds like it: a bare "hey" at 0.26 on the real mic, "Hey Travis" up to 0.94 in a test
    voice. So speech to text must hear the name too. If it can't answer, wake: a lost request is worse than a false wake."""
    try:
        said = transcribe(clip, NAME_TIMEOUT)
    except Exception as e:
        emit("status", text=f"Couldn't check the wake word's words, so waking anyway: {e}")
        return True, ""
    return bool(re.search(rf"\b{NAMES}\b", said, re.IGNORECASE)), said


def greeting_text(word: str, title: str) -> str:
    return f"{word}, {title.lower()}." if title else f"{word}."


def closes(said: str) -> bool:
    """A lone "Thank you." isn't one: it's what Whisper makes of faint sound, and there is no request to send anyway."""
    said = strip_wake(said)
    return bool(CLOSING.search(said)) and " ".join(re.findall(r"\w+", said.lower())) not in HALLUCINATIONS


def sorry(title: str) -> str:
    return f"Sorry {title.lower()}," if title else "Sorry,"


def last_heard(heard: str, heard_at: float, now: float) -> str:
    """The sentence that tells them where it lost the thread, or "" when that's too old to help."""
    if not heard or now - heard_at > HEARD_RECENT:
        return ""
    return f"Last I heard: {' '.join(heard.split()[-HEARD_WORDS:]).rstrip('.!?')}."


def cut_off_line(state: dict, why: str, now: float, title: str = "") -> tuple[str, bool]:
    """What to say on coming back from `state`, the file a stopped listener left, and whether to listen again after it.
    Nothing after a clean quit or a long time off: that's a fresh start."""
    if not state or state.get("clean") or now - state.get("at", 0) > CUT_RECENT:
        return "", False
    phase = state.get("phase")
    parts = [f"{sorry(title)} I got cut off{f' by {why}' if why else ''}."]
    if phase == "talking":
        parts.append("I lost what you were just saying.")
    if said := last_heard(state.get("heard", ""), state.get("heard_at", 0), now):
        parts.append(said)
    if phase in ("talking", "window"):
        parts.append("Go ahead.")
    return " ".join(parts), phase in ("talking", "window")


def why_lost(e: Exception) -> str:
    """In words for the speaker: never the exception's own text."""
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status == 429:
        return "speech to text hit its limit"
    return "speech to text gave an error" if status else "I couldn't reach speech to text"


def read_state() -> dict:
    try:
        return json.loads(EARS_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def quiet_enough(state: dict, now: float) -> bool:
    """A moment to stop the listener without cutting anyone off. A save this old means it's speaking or waiting on speech to
    text, whose blocking calls hold up the saves."""
    return (now - state.get("at", 0) <= 3 * STATE_EVERY and state.get("phase") == "idle" and not state.get("lines")
            and now - state.get("last_speech", 0) >= RESTART_QUIET)


def restart(args: list[str]) -> int:
    """`listener.py restart [--now] [why]`: stops the listener at a quiet moment, for voice.mjs to start it again in a few
    seconds, and it says why it stopped. --now doesn't wait: for testing the line. The only way to restart it."""
    now_please = "--now" in args
    why = " ".join(a for a in args if a != "--now") or "a restart"
    deadline = time.time() + RESTART_WAIT
    while not now_please and not quiet_enough(read_state(), time.time()):
        if time.time() > deadline:
            print(f"Not restarted: no quiet minute in {RESTART_WAIT // 60} minutes.")
            return 1
        time.sleep(2)
    state = read_state()
    if time.time() - state.get("at", 0) > 3 * STATE_EVERY:  # also guards against an old pid, now someone else's
        print("Not restarted: the listener isn't saving its state, so it's off, or speaking right now.")
        return 1
    EARS_WHY.write_text(why, encoding="utf-8")
    os.kill(state["pid"], 15)
    print(f"Stopped the listener ({why}).")
    return 0


def strip_echo(heard: str, said: str, late: bool) -> str:
    """What a clip heard without the end of the reply just spoken, which can open it now the mic opens before the reply
    ends. `late`: there was speech after the reply's end, so a lone last word may be the user's ("Yes or no?" "No.")."""
    spans = list(re.finditer(r"[\w']+", heard.lower()))
    words = [m.group() for m in spans]
    tail = re.findall(r"[\w']+", said.lower())[-ECHO_WORDS:]
    if not words or not tail:
        return heard
    m = difflib.SequenceMatcher(None, tail, words, autojunk=False).find_longest_match(0, len(tail), 0, len(words))
    if m.size == len(words) and (m.size >= 3 or not late):  # all of it is the reply's words
        return ""
    if m.size >= 2 and m.b <= 1 and m.a + m.size >= len(tail) - 1:  # it starts with the reply's last words; the rest is the user
        return heard[spans[m.b + m.size - 1].end():].lstrip(" ,.!?;:-")
    return heard


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


def transcribe(clip: np.ndarray, timeout: int = 600) -> str:
    """ElevenLabs Scribe v2 when set up, else (or when it fails) Groq. Both detect English, Tagalog and Taglish.
    What the engine said about the clip stays in heard_how, for keep_clip."""
    import requests

    global heard_how
    if key := el_key():
        try:
            r = requests.post(f"{EL_URL}/speech-to-text", headers={"xi-api-key": key},
                              files={"file": audio_file(clip)},
                              # The clip can start mid wake word; without the keyterm Scribe mishears it.
                              data={"model_id": "scribe_v2", "tag_audio_events": "false",
                                    "keyterms": [w.replace("_", " ").title() for w in wake_words()] + TERMS[:99]},
                              timeout=timeout)
            r.raise_for_status()
            j = r.json()
            heard_how = {"engine": "scribe", "language": j.get("language_code"),
                         "language_probability": j.get("language_probability")}
            return j["text"].strip()
        except Exception as e:
            emit("error", message=f"ElevenLabs speech to text failed, trying Groq: {e}")
    j = groq_json(clip, timeout)
    heard_how = {"engine": "groq", "language": j.get("language"),
                 "segments": [{k: s.get(k) for k in ("text", "avg_logprob", "compression_ratio", "no_speech_prob")}
                              for s in j.get("segments", [])]}
    return segments_text(j)


def groq_text(clip: np.ndarray, timeout: int = 600) -> str:
    return segments_text(groq_json(clip, timeout))


def segments_text(j: dict) -> str:
    """Whisper, given a prompt, can hear a short request again in the 5 s of quiet that end it: same words, next segment.
    Cutting that quiet stops it but also lost words on real clips, so the repeat goes here."""
    said: list[str] = []
    for s in j.get("segments", []):
        text = s["text"].strip()
        if s["avg_logprob"] > MIN_LOGPROB and (not said or text.lower() != said[-1].lower()):
            said.append(text)
    return " ".join(said).strip()


GROQ_LIMIT = 20  # requests a minute on Groq's free tier, from its error and headers
groq_calls: deque[float] = deque(maxlen=GROQ_LIMIT)  # when this listener last called it


def groq_room(spare: int) -> bool:
    """Whether a nice-to-have request fits, leaving `spare` of the minute's requests for what the user said. Only this
    listener's own calls count."""
    now = time.monotonic()
    return sum(now - t < 60 for t in groq_calls) < GROQ_LIMIT - spare


def groq_json(clip: np.ndarray, timeout: int = 600) -> dict:
    import requests

    groq_calls.append(time.monotonic())
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise RuntimeError("GROQ_API_KEY is missing: put it in .env (free at https://console.groq.com/keys)")
    r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"},
                      files={"file": audio_file(clip)},
                      data={"model": "whisper-large-v3-turbo", "response_format": "verbose_json", "prompt": VOCAB},
                      timeout=timeout)
    if r.status_code == 429 and timeout > 10:  # a request's own words are worth a short wait; checks and live words aren't
        time.sleep(min(5, float(r.headers.get("retry-after") or 3)))
        r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"},
                          files={"file": audio_file(clip)},
                          data={"model": "whisper-large-v3-turbo", "response_format": "verbose_json", "prompt": VOCAB},
                          timeout=timeout)
    r.raise_for_status()
    return r.json()


heard_how: dict = {}  # what the engine said about the last request clip; only transcribe writes it, not the live words


def handed_back(text: str) -> bool:
    """A list with a VOCAB word in it, such as "Rc, Cpd, Su, Toc": Whisper's prompt coming back on a noisy clip, which
    must not reach the orch with a command in it. A real "yes, cpd" goes too, and only has to be said again."""
    parts = [re.findall(r"\w+", part.lower()) for part in text.split(",")]
    parts = [p for p in parts if p]
    terms = {t.lower() for t in TERMS}
    return len(parts) >= 2 and all(len(p) == 1 for p in parts) and any(p[0] in terms for p in parts)


def data_dir() -> Path | None:
    """Where voice data lands: outside C:\\dev, which Syncthing copies to the other machine."""
    root = os.environ.get("LOCALAPPDATA")
    return Path(root) / "free247jarvis" / "voicedata" if root else None


def prune_data() -> None:
    """Deletes clips past DATA_DAYS or over DATA_MAX, oldest first (their names sort by time), and their rows.
    VOICE_DATA=forever deletes nothing."""
    folder = data_dir()
    if not folder or not folder.is_dir() or os.environ.get("VOICE_DATA", "").lower() == "forever":
        return
    clips = sorted(folder.glob("*.wav"))
    total, gone = sum(c.stat().st_size for c in clips), False
    for clip in clips:
        size = clip.stat().st_size
        if time.time() - clip.stat().st_mtime > DATA_DAYS * 86400 or total > DATA_MAX:
            clip.unlink()
            total, gone = total - size, True
    rows = folder / "requests.jsonl"
    if gone and rows.is_file():
        kept = [line for line in rows.read_text(encoding="utf-8").splitlines()
                if (folder / json.loads(line)["clip"]).is_file()]
        rows.with_suffix(".partial").write_text("".join(line + "\n" for line in kept), encoding="utf-8")
        os.replace(rows.with_suffix(".partial"), rows)


def keep_clip(clip: np.ndarray, transcript: str, text: str, score: float, level: int) -> None:
    """A clip that passed the wake word (or fired it with no name in its words), and one row about it, for mishears.py. Opt-in: only with VOICE_DATA=on or
    forever. Not in a call, where a client could be on it. A failure here only goes to the log: the request matters more."""
    folder = data_dir()
    if not folder or os.environ.get("VOICE_DATA", "").lower() not in ("on", "forever"):
        return
    try:
        if in_call():
            return
        folder.mkdir(parents=True, exist_ok=True)
        now = time.time()
        name = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + f"-{int(now * 1000) % 1000:03d}.wav"
        (folder / name).write_bytes(wav_bytes(clip))
        row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), "clip": name,
               "seconds": round(len(clip) / RATE, 1), "transcript": transcript, "kept": bool(text),
               "wake_score": round(score, 2), "level": level, **heard_how}
        with open(folder / "requests.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        prune_data()
    except Exception as e:
        emit("status", text=f"Voice data not kept: {e}")


class ScribeLive:
    """Words on screen while the user speaks, from ElevenLabs Scribe Realtime. For show only: the request's text still
    comes from transcribe(), which got more Taglish right on the far-mic test, so a failure here loses nothing."""

    def __init__(self, key: str) -> None:
        self.key, self.chunks, self.stopped = key, queue.Queue(), False
        threading.Thread(target=self.run, daemon=True).start()

    def feed(self, chunk: np.ndarray) -> None:
        self.chunks.put(chunk)

    def stop(self) -> None:
        self.stopped = True
        self.chunks.put(None)

    def run(self) -> None:
        try:
            from websockets.sync.client import connect

            with connect(SCRIBE_LIVE_URL, additional_headers={"xi-api-key": self.key}, open_timeout=5) as ws:
                threading.Thread(target=self.receive, args=(ws,), daemon=True).start()
                while (chunk := self.chunks.get()) is not None:
                    ws.send(json.dumps({"message_type": "input_audio_chunk", "commit": False, "sample_rate": RATE,
                                        "audio_base_64": base64.b64encode(chunk.tobytes()).decode()}))
        except Exception as e:
            if not self.stopped:
                emit("status", text=f"Live words stopped: {e}")

    def receive(self, ws) -> None:
        try:
            for message in ws:
                event = json.loads(message)
                kind = event.get("message_type", "")
                if self.stopped:
                    return
                if kind == "partial_transcript":
                    emit("partial", text=fix_words(strip_wake(event.get("text", ""))))
                elif kind.endswith(("error", "exceeded", "limited", "terms")):
                    emit("status", text=f"Live words: {kind}")
        except Exception:  # closed: run says why, if it matters
            pass


class GroqLive:
    """The free voice's live words: Groq takes only finished files, so the last LIVE_CLIP chunks go up every LIVE_EVERY
    chunks, one at a time. For show only, as in ScribeLive."""

    def __init__(self) -> None:
        self.clip: deque[np.ndarray] = deque(maxlen=LIVE_CLIP)
        self.waiting, self.busy, self.stopped = 0, False, False

    def feed(self, chunk: np.ndarray) -> None:
        self.clip.append(chunk)
        self.waiting += 1
        if self.waiting >= LIVE_EVERY and not self.busy and groq_room(LIVE_SPARE):
            self.waiting, self.busy = 0, True
            threading.Thread(target=self.ask, args=(np.concatenate(self.clip),), daemon=True).start()

    def stop(self) -> None:
        self.stopped = True

    def ask(self, clip: np.ndarray) -> None:
        try:
            text = strip_wake(groq_text(clip, timeout=10))
            if text and not self.stopped and " ".join(re.findall(r"\w+", text.lower())) not in HALLUCINATIONS:
                emit("partial", text=fix_words(text))
        except Exception as e:  # such as the rate limit: the next try may pass, and the request's own text is apart
            emit("status", text=f"Live words skipped: {e}")
        finally:
            self.busy = False


def live_words():
    """Live words for the voice in use; None when there is no key for them."""
    if key := el_key():
        return ScribeLive(key)
    return GroqLive() if os.environ.get("GROQ_API_KEY") else None


class Ears:
    """Turns 80 ms microphone chunks into events: waits for the wake word, then records until the speaker stops."""

    watching = False  # the window is open: worth paying for live words
    live = None  # the live words of the clip being recorded
    woke = None  # (score, level) while the clip being recorded came from the wake word, not a follow-up window
    sure = False  # it woke while staying quiet: a shorter clip, none of it kept
    need_name = True  # speech to text must hear "Jarvis" before it wakes; WAKE_NAME=off leaves it to the score alone
    cap = MAX_CLIP  # chunks the clip being recorded may reach
    lead, said, words_end = LISTEN_LEAD, "", 0.0  # the reply last spoken, and when its last word reached the mic
    banked: dict = {}  # lines rendered ahead, by their words
    waiting: list = []  # lines about something that waits on the user
    reminded: dict = {}  # when each of them last followed a greeting
    reminders = True  # REMINDERS=off: never
    idle_window = False  # the window now open follows a line that asked nothing
    sounds = True  # False: no chimes, whatever the files say (SOUNDS=off)
    listen_all, mic_open = True, True  # listen_all: a window after every line (LISTEN_AFTER=asked: only after a question)
    closing_gap, next_closing, voiced_at = round(CLOSING_GAP / 0.08), 0.0, 0  # voiced_at: chunks in when the speech last was
    greetings, greetings_at, greeted, last_greeting = (), {}, 0.0, ""  # all rendered; greetings is empty with GREETING=off
    strict, talk_share = WAKE_STRICT, TALK_SHARE
    quiet_why, next_quiet = "", 0.0
    cut_off = True  # CUT_OFF=off: says nothing about a stop or a lost request
    heard_last, heard_at, lost_at = "", 0.0, 0.0  # the last request heard, kept in EARS_STATE; when a loss was last said
    coming_back = None  # (line, listen after it) until the mic opens
    saved_phase, saved_at = "", 0.0

    def phase(self) -> str:
        if self.on_chunk == self.wake_chunk or self.on_done == self.take_done:
            return "idle"
        return "talking" if self.voiced >= MIN_VOICED else "window"

    def save_state(self, clean: bool = False) -> None:
        """What the next listener needs if this one stops: at once when it changes, else every STATE_EVERY seconds."""
        now, phase = time.time(), self.phase()
        if not clean and phase == self.saved_phase and now - self.saved_at < STATE_EVERY:
            return
        self.saved_phase, self.saved_at = phase, now
        spoke = now - (time.monotonic() - self.last_speech) if self.last_speech else 0
        try:
            partial = EARS_STATE.with_suffix(".partial")
            partial.write_text(json.dumps({"pid": os.getpid(), "at": now, "phase": phase, "clean": clean, "last_speech": spoke,
                                           "lines": len(self.queue), "heard": self.heard_last, "heard_at": self.heard_at}), encoding="utf-8")
            os.replace(partial, EARS_STATE)
        except OSError:  # a moment's lock on the file: the next save makes up for it
            self.saved_at = 0.0

    def came_back(self) -> None:
        """Reads what the last listener left. The line waits for the mic, in say_cut_off."""
        state = read_state()
        self.heard_last, self.heard_at = state.get("heard", ""), state.get("heard_at", 0.0)
        try:
            why = EARS_WHY.read_text(encoding="utf-8").strip()
            EARS_WHY.unlink()
        except OSError:
            why = ""
        text, listen = cut_off_line(state, why, time.time(), os.environ.get("VOICE_TITLE") or "")
        self.coming_back = (text, listen) if text else None

    def say_cut_off(self) -> None:
        """A moment to hear whether the user is talking first (SPOKE_WAIT, through user_turn), since it came back blind. Held
        in a call, like news. Only a stop during a window or a request listens again."""
        coming_back, self.coming_back = self.coming_back, None
        if coming_back and self.cut_off:
            text, listen = coming_back
            self.last_speech = time.monotonic()
            emit("cut_off", text=text)
            self.line(text, asked=listen, hold=True, window=listen, toast=False)

    def lost(self, e: Exception) -> None:
        """A request's words never came back: say so, rather than silence, and listen for it again."""
        emit("error", message=f"Request lost: {e}")
        self.release()
        emit("nothing")
        now = time.monotonic()
        if self.cut_off and now - self.lost_at >= LOST_GAP:
            self.lost_at = now
            parts = [f"{sorry(os.environ.get('VOICE_TITLE') or '')} I lost that: {why_lost(e)}.",
                     last_heard(self.heard_last, self.heard_at, time.time()), "Say it again."]
            text = " ".join(p for p in parts if p)
            emit("lost", text=text)
            self.line(text, hold=True, toast=False)

    def __init__(self) -> None:
        from kokoro_onnx import Kokoro
        from openwakeword.vad import VAD

        emit("status", text="Loading the wake word and the voice...")
        fetch()
        self.words = wake_words()
        self.oww = wake_model(self.words)
        self.threshold = float(os.environ.get("WAKE_THRESHOLD") or 0.5)  # here, not at import: .env loads later
        self.strict = max(self.threshold, float(os.environ.get("WAKE_STRICT") or WAKE_STRICT))
        self.talk_share = float(os.environ.get("TALK_SHARE") or TALK_SHARE)
        self.need_name = os.environ.get("WAKE_NAME", "").lower() != "off"
        self.lead = float(os.environ.get("LISTEN_LEAD") or LISTEN_LEAD)
        self.banked, self.waiting, self.reminded = {}, [], {}
        self.spoke: deque[bool] = deque(maxlen=TALK_CHUNKS)
        self.vad = VAD(str(MODELS / "silero_vad.onnx"))
        self.vad_boost = float(os.environ.get("VAD_BOOST") or 1)  # the wake word and speech to text cope without it
        self.tts = Kokoro.from_session(kokoro_session(), str(MODELS / KOKORO[1]))  # also the fallback for ElevenLabs
        emit("status", text="Voice: ElevenLabs" if el_key() else "Voice: Groq and Kokoro")
        emit("status", text=f"Kokoro on the {'GPU' if 'CUDA' in self.tts.sess.get_providers()[0] else 'CPU'}")
        self.acks = {WAKES[w][0]: self.load_ack(WAKES[w][1]) for w in self.words}  # by model name, as scores are
        self.read_settings()
        self.deaf_until = 0.0  # audio recorded before this moment was our own voice coming out of the speaker
        self.recent: deque[np.ndarray] = deque(maxlen=NAME_ROLL)
        self.paused: list = []  # media sessions paused for an exchange, resumed when it is over
        self.raised: tuple[int, bool] | None = None  # the orch's window, shown because that paused something
        self.reply_by = 0.0  # a request was heard: the video stays paused for its reply until this moment
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

    def stop_live(self) -> None:
        if self.live:
            self.live.stop()
            self.live = None

    def wait_for_wake(self, keep: bool = False) -> None:
        self.stop_live()
        self.woke, self.sure, self.idle_window = None, False, False
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
        speech = self.vad.predict(louder, frame_size=640) >= SPEECH  # about 0.6 ms per chunk
        self.spoke.append(speech)
        return speech

    def talking(self) -> bool:
        """Speech around that nobody woke it for. The VAD can't tell who, so a video's voices count, and it can't hear
        what the mic can't: a call in headphones with the user silent."""
        return len(self.spoke) >= TALK_MIN and sum(self.spoke) / len(self.spoke) >= self.talk_share

    def busy(self) -> bool:
        """The user may be with someone else: no line that nobody asked for, no listening window, no toast."""
        return in_call() or self.talking()

    def report_quiet(self) -> None:
        now = time.monotonic()
        if now >= self.next_quiet:
            self.next_quiet = now + QUIET_EVERY
            why = (call_why or "a call") if in_call() else "people talking" if self.talking() else ""
            if why != self.quiet_why:
                self.quiet_why = why
                emit("quiet", on=bool(why), text=why)

    def wake_chunk(self, chunk: np.ndarray) -> None:
        if self.is_speech(chunk):
            self.last_speech = time.monotonic()
        self.report_quiet()
        self.recent.append(chunk)
        scores = self.oww.predict(chunk)
        fired = max(scores, key=scores.get)
        score = float(scores[fired])
        if score >= PEAK_FLOOR:
            self.peak_level = max(self.peak_level, int(np.sqrt(np.mean(chunk.astype(np.float64) ** 2))))
        sure = score >= self.threshold and self.busy()
        if score >= (self.strict if sure else self.threshold):
            emit("peak", word=fired, score=round(score, 2), level=self.peak_level)
            level, self.peak_level = self.peak_level, 0
            if self.need_name:
                clip = np.concatenate(list(self.recent))
                named, said = name_check(clip)
                if not named:  # no sound, no pause: to the user, nothing happened
                    emit("status", text="The wake word fired, but its words had no Jarvis: ignored")
                    if not sure:  # staying quiet: other people may be on the clip
                        keep_clip(clip, said, "", score, level)
                    self.wait_for_wake(keep=True)  # keep: a video paused for an earlier request stays paused
                    self.tried(stray=True)
                    return
            self.woke, self.sure = (score, level), sure
            emit("wake")  # also while the boss works on the last request: this one reaches it as a new message
            self.hush()  # first, so the video's sound stays out of the request            # Heard the wake word: short and undrained, so little of a one-breath request is lost. Its blip is at the
            # start of a longer file, so the stream closing early doesn't reach it.
            self.greet(sure)
            self.record(self.request_done, list(self.recent)[-PRE_ROLL:])
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

    def read_settings(self) -> None:
        """What the window's settings can change, from the environment: at the start, and on `set` with no restart."""
        env = os.environ
        self.sounds = env.get("SOUNDS", "").lower() != "off"
        self.reminders = env.get("REMINDERS", "").lower() != "off"
        self.cut_off = env.get("CUT_OFF", "").lower() != "off"
        self.listen_all = env.get("LISTEN_AFTER", "").lower() != "asked"
        self.followup = round(float(env.get("FOLLOWUP_SECONDS") or 8) / 0.08)  # in chunks; 0: off
        # 0 chunks: no cut-off.
        self.closing_gap = 0 if env.get("CLOSING_CUT", "").lower() == "off" else round(float(env.get("CLOSING_GAP") or CLOSING_GAP) / 0.08)
        if env.get("GREETING", "").lower() == "off":
            self.greetings, self.greetings_at = (), {}
        elif not self.greetings:
            self.load_greetings()

    def load_greetings(self) -> None:
        """Each greeting without its silence at the ends. A voice that fails leaves the chime, and the next start tries again."""
        title = (os.environ.get("VOICE_TITLE") or "").strip()

        def render(word: str):
            text = greeting_text(word, title)
            samples, rate = self.load_ack(text, GREETING_SPEED)
            loud = np.flatnonzero(np.abs(samples) > 0.01)
            if not len(loud):
                return None
            samples = samples[max(0, loud[0] - rate // 100):loud[-1] + rate // 20]
            return (text, samples, rate) if len(samples) / rate <= GREETING_MAX else None

        try:
            self.greetings = [g for g in map(render, GREETINGS) if g]
            self.greetings_at = {word: g for word in GREETINGS_AT if (g := render(word))}
            emit("status", text=f"{len(self.greetings) + len(self.greetings_at)} greetings ready")
        except Exception as e:
            self.greetings, self.greetings_at = (), {}
            emit("error", message=f"No greetings, so the chime: {e}")

    def greet(self, sure: bool) -> None:
        """Lets the user know it heard: a few spoken words, different each time. While they're with someone, only the chime.
        The mic keeps counting meanwhile, so "Hey Jarvis, status" in one breath loses nothing to it."""
        if sure or not self.greetings:
            self.play(*CHIME_UP, tail=0.05, drain=False)
            return
        now = time.monotonic()
        hour = time.localtime().tm_hour
        due = next((g for word, g in self.greetings_at.items() if hour in GREETINGS_AT[word]), None)
        if due and (not self.greeted or now - self.greeted > GREETING_AWAY):
            line = due
        else:
            line = random.choice([g for g in self.greetings if g[0] != self.last_greeting] or self.greetings)
        text, samples, rate = line
        self.greeted, self.last_greeting = now, text
        emit("greeting", text=text)
        self.play(samples, rate)
        # One thing that waits on the user, at most, and not the same one again soon. None in a call: that's the chime above.
        extra = next((w for w in self.waiting if self.reminders and w in self.banked
                      and now - self.reminded.get(w, -REMIND_EVERY) >= REMIND_EVERY), None)
        if extra:
            self.reminded[extra] = now
            emit("reminder", text=extra)
            self.play(*self.banked[extra])
        self.said, self.words_end = f"{text} {extra}" if extra else text, time.monotonic() - 0.07
        self.deaf_until = now

    def tried(self, stray: bool = False) -> None:
        """A try at the wake word got nowhere. Repeated, the user is looking for it and may not hear its sounds. A
        near miss could be a video or the other side of a call (stray), so those two keep it quiet."""
        now = time.monotonic()
        self.tries = [t for t in self.tries if now - t < LOOK_WINDOW] + [now]
        if len(self.tries) >= LOOK_TRIES:
            self.tries = []
            if not self.busy() and not (stray and media_playing()):
                emit("caption", text=self.looking(), looking=True)

    def looking(self) -> str:
        return f"Hello, I'm Jarvis, and I can hear you. {output_problem() or CANT_HEAR}"

    def cue(self, sound: tuple[np.ndarray, int]) -> None:
        """A sound that answers a try at the wake word: at most one per CUE_GAP, and none in a call."""
        if time.monotonic() >= self.next_cue and not self.busy():
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
            # The wake chime already played (it replaced the spoken "Jarvis here").
            self.record(self.request_done)

    def record(self, on_done, start=(), give_up: int = GIVE_UP) -> None:
        """Collects chunks until the speaker stops, then calls on_done with the clip, or with None if nobody spoke
        within give_up chunks."""
        self.stop_live()
        self.vad.reset_states()
        self.clip, self.voiced, self.quiet, self.on_done, self.give_up = list(start), 0, 0, on_done, give_up
        self.voiced_at = 0
        self.cap = MAX_CLIP if self.woke and not self.sure else SHORT_CLIP
        self.on_chunk = self.record_chunk

    def record_chunk(self, chunk: np.ndarray) -> None:
        self.clip.append(chunk)
        if self.is_speech(chunk):
            self.voiced, self.quiet = self.voiced + 1, 0
            self.voiced_at = len(self.clip)
            self.last_speech = time.monotonic()
            # From the first speech, so a false wake or an unused follow-up window costs nothing. Not voice training.
            if self.voiced == 1 and self.watching and not self.live and self.on_done != self.take_done:
                self.live = live_words()
                for earlier in self.clip[:-1]:
                    self.live and self.live.feed(earlier)
        else:
            self.quiet += 1
        if self.live:
            self.live.feed(chunk)
        spoke = self.voiced >= MIN_VOICED
        # Nobody's answer runs this long: a conversation the window caught, tonight 852 words of it. Nothing is sent.
        if self.cap < MAX_CLIP and len(self.clip) >= self.cap:
            emit("status", text="Too long for a reply: dropped unsent")
            self.wait_for_wake()
            return
        if (spoke and self.quiet >= END_QUIET) or (not spoke and len(self.clip) >= self.give_up) or len(self.clip) >= MAX_CLIP \
                or (spoke and self.quiet == self.closing_gap and self.said_closing()):
            self.stop_live()
            self.on_done(np.concatenate(self.clip) if spoke else None)

    def said_closing(self) -> bool:
        """The speech so far ends with a closing phrase. Blocks for a moment; the mic's chunks wait in the queue, so if the
        user goes on, nothing is lost and the next pause checks again. Any failure leaves it to silence."""
        now = time.monotonic()
        if not self.closing_gap or self.on_done == self.take_done or now < self.next_closing or not groq_room(CLOSING_SPARE):
            return False
        self.next_closing = now + CLOSING_EVERY
        if self.live:
            self.live.waiting = 0  # this request takes the live words' turn, for Groq's limit
        try:
            said = transcribe(np.concatenate(self.clip[max(0, self.voiced_at - CLOSING_TAIL):self.voiced_at + 2]), CLOSING_TIMEOUT)
        except Exception as e:
            emit("status", text=f"Closing phrase not checked: {e}")
            return False
        if not closes(said):
            return False
        emit("status", text="Closing phrase: sent without waiting for the silence")
        return True

    def request_done(self, clip: np.ndarray | None) -> None:
        began = time.monotonic() - len(clip) / RATE if clip is not None else 0.0
        late = began + self.voiced_at * CHUNK / RATE > self.words_end + ECHO_ROOM
        self.play(*(CHIME_DOWN if clip is not None else CHIME_CLOSE), tail=0.1)  # heard you, or stopped listening
        woke, sure = self.woke, self.sure
        self.wait_for_wake(keep=clip is not None)  # first, so a failed transcription still leaves the ears listening
        try:
            transcript = transcribe(clip) if clip is not None else ""
        except Exception as e:
            return self.lost(e)
        text = strip_wake(transcript)
        if clip is not None and self.said and began < self.words_end + 2:  # 2: the queue can run behind
            clean = strip_echo(text, self.said, late)
            if clean != text:
                emit("status", text="Took out what it heard of its own reply")
            text = clean
        words = re.findall(r"\w+", text.lower())
        if set(words) <= set(re.findall(r"\w+", VOCAB.lower())) or " ".join(words) in HALLUCINATIONS or handed_back(text):
            text = ""  # nothing, Whisper's prompt handed back, or what Whisper says for noise
        if clip is not None and woke and not sure:  # staying quiet: other people may be on the clip
            keep_clip(clip, transcript, text, *woke)
        if text:
            self.spoke.clear()  # that was the user talking to it, not people talking
            self.tries = []
            self.reply_by = time.monotonic() + REPLY_HOLD
            fixed = fix_words(text)
            self.heard_last, self.heard_at, self.saved_at = fixed, time.time(), 0.0  # saved_at: on disk right away
            emit("heard", text=fixed, **({"raw": text} if fixed != text else {}))  # raw: for the window, as heard
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
            # A window after a line that asked nothing, with nobody speaking into it: news doesn't wait it out.
            return not (self.idle_window and not self.voiced)
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

    def say(self, text: str, asked: bool = True, hold: bool = False, window: bool = True, toast: bool = True) -> None:
        """Speaks a line with Kokoro, media paused, and keeps a copy in tmp/reply.wav. The caller mutes the mic
        meanwhile. Only a line that wants an answer (asked and window) opens the follow-up window, and never while
        staying quiet, so other people's audio is not sent to speech to text. With hold, staying quiet keeps the line
        back unsaid as `held`."""
        import soundfile as sf

        call = self.busy()
        if call and hold:
            emit("held", text=text)
            return
        listen = bool(self.followup) and asked and window and not call
        if hold and listen and toast:
            emit("caption", text=text, remind=True)  # nobody prompted it and it needs them: a notification too
        wanted = listen
        listen = listen or (self.listen_all and bool(self.followup) and self.mic_open and not call)  # never in a call or room talk
        samples, rate, _ = self.speech(text)
        REPLY_WAV.parent.mkdir(exist_ok=True)
        sf.write(REPLY_WAV.with_suffix(".partial.wav"), samples, rate)
        os.replace(REPLY_WAV.with_suffix(".partial.wav"), REPLY_WAV)
        emit("said", wav=str(REPLY_WAV), text=text)
        words_len = len(samples)
        if listen and self.sounds and rate == CHIME_UP[1]:  # the chime in the same stream, the instant the words end
            samples = np.concatenate([samples.astype(np.float32), np.zeros(rate * 6 // 10, np.float32), CHIME_UP[0]])  # 0.7 s after the last word
        self.hush()
        problem = output_problem()  # not caught by the sound failing: a muted speaker plays along silently
        if problem:
            emit("caption", text=f"{problem} I said: {text}")
        if not self.play(samples, rate) and not problem:
            emit("caption", text=f"I can't play sound. {CANT_HEAR} I said: {text}")
        # Measured at the mic: the last word arrives about 0.07 s before play() returns (DRAIN, less what the speaker holds back).
        self.said, self.words_end = text, time.monotonic() - (len(samples) - words_len) / rate - 0.07
        opened = self.words_end - self.lead
        self.deaf_until = opened
        emit("spoken", listening=listen)
        if listen:  # the user may answer without the wake word for a few seconds, then it waits for it again
            if rate != CHIME_UP[1]:
                self.play(*CHIME_UP, tail=0.15)  # the mic is open again
                self.deaf_until = opened
            self.record(lambda clip: self.request_done(clip) if clip is not None else self.close(),
                        give_up=self.followup)
            self.idle_window = not wanted
        else:
            self.wait_for_wake(keep=not asked and bool(self.reply_by))  # news meanwhile: the reply is still to come

    def play(self, samples: np.ndarray, rate: int, tail: float = ECHO, drain: bool = True) -> bool:
        """Plays it with the mic deaf until `tail` seconds after the end. False if it could not play."""
        played = True
        if not self.sounds and any(samples is s[0] for s in (CHIME_UP, CHIME_DOWN, CHIME_CLOSE, CHIME_NEAR)):
            self.deaf_until = time.monotonic() + min(tail, 0.05)
            return True
        try:
            import sounddevice as sd

            sd.play(np.concatenate([samples, np.zeros(int(rate * DRAIN), samples.dtype)]) if drain else samples, rate)
            sd.wait()
        except Exception as e:  # no speaker: a reply's wav is still there
            emit("error", message=f"Can't play: {e}")
            played = False
        self.deaf_until = time.monotonic() + tail
        return played

    def load_ack(self, text: str, speed: float = 1.0) -> tuple[np.ndarray, int]:
        """`text` in the current voice, rendered once per voice and cached in tmp/, so it plays the moment it's needed."""
        import soundfile as sf

        name = re.sub(r"\W", "", text.lower()) + (f"_{speed}" if speed != 1 else "")
        if len(name) > 60:  # a whole progress line: too long for a file name
            name = f"{name[:40]}{zlib.crc32(name.encode()):08x}"
        path = HERE / "tmp" / f"{name}_{voice_key()}.wav"
        if not path.is_file():
            samples, rate, used = self.speech(text, speed)
            path = HERE / "tmp" / f"{name}_{used}.wav"  # Kokoro's when ElevenLabs failed; it is tried again next start
            path.parent.mkdir(exist_ok=True)
            sf.write(path, samples, rate)
        return sf.read(path, dtype="float32")

    def speech(self, text: str, speed: float = 1.0) -> tuple[np.ndarray, int, str]:
        """The reply as audio, plus the voice_key() that said it: the ElevenLabs voice when set up, else (or when it
        fails) Kokoro. A line rendered ahead, with an age after it that is too, needs neither."""
        for line, (samples, rate) in self.banked.items():
            rest = text[len(line):].strip() if text.startswith(line) else None
            if rest == "":
                return samples, rate, voice_key()
            if rest and rest in self.banked and self.banked[rest][1] == rate:
                pause = np.zeros(rate // 8, np.float32)
                return np.concatenate([samples.astype(np.float32), pause, self.banked[rest][0].astype(np.float32)]), rate, voice_key()
        engine, _, voice = voice_key().partition("_")
        if engine == "elevenlabs":
            import requests

            try:
                r = requests.post(f"{EL_URL}/text-to-speech/{voice}",
                                  params={"output_format": "pcm_24000"}, headers={"xi-api-key": el_key()}, timeout=30,
                                  json={"text": text, "model_id": os.environ.get("ELEVENLABS_MODEL") or "eleven_flash_v2_5",
                                        **({"voice_settings": {"speed": speed}} if speed != 1 else {})})
                r.raise_for_status()
                return np.frombuffer(r.content, np.int16).astype(np.float32) / 32768, 24000, f"elevenlabs_{voice}"
            except Exception as e:
                emit("error", message=f"ElevenLabs voice failed, using Kokoro: {e}")
            voice = os.environ.get("VOICE") or "bm_george"
        # bm_/bf_ voices are British, so en-gb.
        samples, rate = self.tts.create(text, voice=voice, speed=speed, lang="en-gb" if voice[0] == "b" else "en-us")
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


def mic_name(stream) -> str:
    """The device this open stream reads, for the window: its real ID, also when it opened as Windows' default."""
    import sounddevice as sd

    try:
        return sd.query_devices(stream.device)["name"]
    except Exception as e:
        emit("status", text=f"Can't name the microphone: {e}")
        return ""


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
    try:
        prune_data()  # also with VOICE_DATA=off or no new requests: old clips still go
    except Exception as e:
        emit("status", text=f"Voice data not pruned: {e}")
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
    ears.came_back()
    mic = None

    def report() -> None:
        emit("state", on=mic is not None, mic=mic_name(mic) if mic is not None else "", trained=verifier(ears.words[0]).is_file())

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
                    report()
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
                ears.save_state()
            continue
        if value == "quit":
            ears.save_state(clean=True)  # the voice is closing on purpose: nothing to apologize for next time
            break
        if value.startswith("bank "):  # a line to have ready, from the status bank; a failure just means live speech later
            try:
                ears.banked[value[5:]] = ears.load_ack(value[5:])
            except Exception as e:
                emit("status", text=f"Not rendered ahead: {e}")
            continue
        if value.startswith("waiting "):  # what may follow a greeting: "waiting" the whole list, as JSON
            ears.waiting = json.loads(value[8:])
            continue
        if value.startswith("set "):  # from the window's settings; voice.mjs checks the name and value, and saves them
            _, key, *rest = value.split(" ", 2)
            os.environ[key] = rest[0] if rest else ""
            ears.read_settings()
            continue
        if value == "looking":
            emit("caption", text=ears.looking(), looking=True)
            continue
        if value in ("watch on", "watch off"):
            ears.watching = value == "watch on"
            continue
        if value == "listen":  # after "Say that again?": record the next sentence without the wake word
            if not ears.queue and not ears.busy():
                ears.record(ears.request_done)
            continue
        if value.startswith(("say ", "end ", "late ", "tell ")):
            verb, text = value.split(" ", 1)
            # With the mic closed no window can open or end, and paused media would never resume.
            ears.mic_open = mic is not None
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
        report()
        if value == "on" and mic is not None:
            ears.say_cut_off()
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
    elif arg == "restart":
        sys.exit(restart(sys.argv[2:]))
    else:
        try:
            main([])
        except Exception:
            EARS_WHY.write_text("a crash", encoding="utf-8")
            raise
