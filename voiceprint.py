"""Is this request clip the user's voice? For VOICE_MATCH=on (listener.py): each request is compared with a voiceprint
made from the user's kept clips. Offline, on the CPU, one ONNX model: 3D-Speaker CAM++ (Apache-2.0), from the sherpa-onnx
release speaker-recongition-models, 192 numbers per clip. Its input is Kaldi fbank (80 bins, 25 ms frames every 10 ms),
with the average frame taken off each bin, and clips are compared by cosine score.

  python voiceprint.py enroll   build the voiceprint from the kept requests (run again after new voice data)
  python voiceprint.py test     the pure parts' checks (no model needed)
"""
import json
import os
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODELS = HERE / "models"
MODEL = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/" + MODEL
MODEL_SHA256 = "53cab20ba8f2eb2f6e2d89ecc18e88ef3222169b61b4419cbc13666744a4574b"  # checked 2026-11-23
RATE = 16000
CHUNK = 1280  # 80 ms, the listener's chunk
MAX_SPEECH = 10 * RATE  # 10 s of speech at most: CPU time 14 ms for 1 s, 47 ms for 5 s, 93 ms for 10 s, 292 ms for 30 s (2026-11-23)
# The bar a clip must reach, by how much speech it holds, as a share of VOICE_MATCH_MIN (0.3, the bar from 4 s on): 0.05 at
# 0.5 s, 0.15 at 1 s, 0.25 at 2 s, straight lines between. Under MIN_SPEECH a clip is not judged at all. Measured 2026-11-23:
# 330 of the user's kept requests in two halves, each half's voiceprint scoring the other half's cuts (436 to 564 a length),
# against 22 LibriSpeech speakers (219 utterances, another mic, so a stranger in this room may score nearer):
#   speech   the user's 1st percentile, median   strangers' median, 99th   at the bar: the user dropped, strangers dropped
#   0.3 s    0.00  0.28                           0.04  0.25                0.00: 1.4%  33%   (so not judged)
#   0.5 s    0.06  0.39                           0.02  0.27                0.05: 0.9%  63%
#   1 s      0.20  0.54                           0.00  0.30                0.15: 0.4%  89%
#   2 s      0.39  0.66                           0.01  0.30                0.25: 0.4%  97%
#   4 s      0.50  0.74                           0.01  0.30                0.30: 0.5%  99%
#   10 s     0.55  0.78                          -0.01  0.28                0.30: 0.0%  100%
# About 0.2% of the user's cuts score under 0 at any length: another voice inside a clip of theirs (a video, a second person).
BAR_AT, BAR_SHARE = (0.5, 1.0, 2.0, 4.0), (1 / 6, 1 / 2, 5 / 6, 1.0)
MIN_SPEECH = 0.5
ENROLL_MIN = 2.0  # seconds of speech a kept clip needs to count toward the voiceprint: a short one scores low against it
HEAD = 38 * CHUNK  # enroll: a kept clip's first 3 s hold the wake word and the echo of the greeting (listener.py TURN_SKIP)
EXEC = ThreadPoolExecutor(1)  # one clip at a time; the ONNX session itself uses 2 threads


def voiceprint_path() -> Path | None:
    """Next to the voice data, outside C:\\dev (Syncthing copies that to the other machine): a voiceprint is biometric."""
    root = os.environ.get("LOCALAPPDATA") or (str(Path.home() / "Library" / "Application Support") if sys.platform == "darwin" else "")
    return Path(root) / "free247jarvis" / "voiceprint.npz" if root else None


def fbank(x: np.ndarray) -> np.ndarray:
    """Kaldi fbank of float samples (-1 to 1, 16 kHz): 80 mel bins, 25 ms frames every 10 ms, pre-emphasis 0.97, Povey window,
    512-point FFT, log power floored at float32 epsilon, no dither. Same numbers as kaldi-native-fbank (checked 2026-11-23)."""
    n, hop, size = 400, 160, 512
    if len(x) < n:
        return np.zeros((0, 80), np.float32)
    frames = (len(x) - n) // hop + 1
    f = x[np.arange(n)[None, :] + hop * np.arange(frames)[:, None]].astype(np.float64)
    f = f - f.mean(axis=1, keepdims=True)  # remove each frame's DC offset
    f = np.concatenate([f[:, :1] * (1 - 0.97), f[:, 1:] - 0.97 * f[:, :-1]], axis=1)  # pre-emphasis
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / (n - 1))) ** 0.85  # Povey window
    power = np.abs(np.fft.rfft(f * win, size)[:, : size // 2]) ** 2  # the top bin is left out, as kaldi does
    mel = lambda hz: 1127 * np.log(1 + hz / 700)
    lo, hi = mel(20.0), mel(RATE / 2)
    delta = (hi - lo) / 81  # 80 triangles, each spanning 2 deltas
    left = lo + delta * np.arange(80)[:, None]
    m = mel(np.arange(size // 2) * RATE / size)[None, :]
    up = np.where((m > left) & (m <= left + delta), (m - left) / delta, 0.0)
    down = np.where((m > left + delta) & (m < left + 2 * delta), (left + 2 * delta - m) / delta, 0.0)
    banks = up + down  # (80, 256)
    return np.log(np.maximum(power @ banks.T, np.finfo(np.float32).eps)).astype(np.float32)


_vad = None


def speech(clip: np.ndarray, boost: float = 0.0) -> np.ndarray:
    """Only the speech of an int16 clip, as floats: the 80 ms chunks Silero calls speech, heard the way the listener hears
    them (Ears.is_speech: a copy made VAD_BOOST louder), plus the chunk either side of each run for a word's edges. It stops
    once MAX_SPEECH is found. Its own Silero, never the listener's: that one keeps state and runs on another thread.
    2026-11-23: a filter by loudness kept all of every clip on this quiet mic, room noise and the silent tail too (median
    share kept 1.00, Silero 0.49 over 140 clips), and a second of the user then scored like a stranger."""
    global _vad
    if _vad is None:
        from openwakeword.vad import VAD

        _vad = VAD(str(MODELS / "silero_vad.onnx"))
    boost = boost or float(os.environ.get("VAD_BOOST") or 1)
    chunks = clip[: len(clip) // CHUNK * CHUNK].reshape(-1, CHUNK)
    heard = np.zeros(len(chunks), bool)
    _vad.reset_states()
    for i, chunk in enumerate(chunks):
        louder = np.clip(chunk.astype(np.float64) * boost, -32768, 32767).astype(np.int16)
        heard[i] = _vad.predict(louder, frame_size=640) >= 0.5
        if heard.sum() * CHUNK >= MAX_SPEECH:
            break
    keep = heard.copy()
    keep[1:] |= heard[:-1]
    keep[:-1] |= heard[1:]
    return chunks[keep].ravel()[:MAX_SPEECH].astype(np.float32) / 32768


_session = None


def session():
    """The model, once. Its file must match MODEL_SHA256, or nothing is judged."""
    global _session
    if _session is None:
        import hashlib
        import onnxruntime as ort

        path = MODELS / MODEL
        if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise RuntimeError("the speaker model's SHA-256 differs")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads, opts.inter_op_num_threads = 2, 1
        _session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
    return _session


def embed(x: np.ndarray) -> np.ndarray:
    """Float samples (speech only) to a unit-length voiceprint vector of 192 numbers."""
    f = fbank(x)
    f = f - f.mean(axis=0)  # the model's "global-mean" feature normalization
    e = session().run(None, {"x": f[None]})[0][0]
    return e / np.linalg.norm(e)


def fetch_model() -> None:
    """Downloads the model once (28 MB), and checks its SHA-256. Called when VOICE_MATCH is on, and by enroll."""
    import hashlib
    import requests

    path = MODELS / MODEL
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA256:
        return
    MODELS.mkdir(exist_ok=True)
    r = requests.get(MODEL_URL, timeout=300)
    r.raise_for_status()
    part = path.with_suffix(".partial")
    part.write_bytes(r.content)
    if hashlib.sha256(r.content).hexdigest() != MODEL_SHA256:
        part.unlink()
        raise RuntimeError("the speaker model's SHA-256 differs from the pinned one")
    os.replace(part, path)


def warm() -> None:
    """Fetches and loads the model ahead of the first request (a thread, when VOICE_MATCH turns on). Failures show up
    on each judged clip as "unsure", so nothing is raised here."""
    try:
        fetch_model()
        session()
    except Exception:
        pass


def drop_outliers(E: np.ndarray) -> np.ndarray:
    """A mask of the rows that belong to the dominant voice: score each against the mean of the kept rows, drop those more
    than 3 robust deviations (MAD) below the median, and repeat up to 3 times. Other voices, or a video, score low."""
    keep = np.ones(len(E), bool)
    for _ in range(3):
        c = E[keep].mean(axis=0)
        s = E @ (c / np.linalg.norm(c))
        med = np.median(s[keep])
        mad = 1.4826 * np.median(np.abs(s[keep] - med))
        new = s >= med - 3 * mad
        if (new == keep).all():
            break
        keep = new
    return keep


GENUINE_MIN = 0.5  # 2026-11-23: after the outlier drop, a kept clip under this against the centroid is not counted as the
# user (those under 0.25 were a video, Jarvis's own reply and a second voice; 0.25 to 0.5 is mostly the user with little speech)


def keep_voice(E: np.ndarray) -> np.ndarray:
    """The genuine set: drop_outliers, then the clips under GENUINE_MIN against the centroid of what is left."""
    keep = drop_outliers(E)
    c = E[keep].mean(axis=0)
    return keep & (E @ (c / np.linalg.norm(c)) >= GENUINE_MIN)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16)


def enroll() -> str:
    """Reads the kept requests (requests.jsonl, kept: true: the wake word heard them), past each one's first 3 s, drops
    the outliers, and saves the voiceprint with what made it (model, counts, each clip's score against the others)."""
    out = voiceprint_path()
    if out is None:
        return "No LOCALAPPDATA here: nothing to save the voiceprint to."
    fetch_model()
    folder = out.parent / "voicedata"
    if not (folder / "requests.jsonl").is_file():
        return f"No kept requests in {folder}: set VOICE_DATA=on, use the voice for a while, then run this again."
    rows = [json.loads(line) for line in (folder / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if r.get("kept") and (folder / r["clip"]).is_file()]
    embs, secs = [], []
    for r in rows:
        x = speech(read_wav(folder / r["clip"])[HEAD:])
        if len(x) / RATE >= ENROLL_MIN:
            embs.append(embed(x))
            secs.append(len(x) / RATE)
    if len(embs) < 20:
        return f"Only {len(embs)} kept requests with {ENROLL_MIN:.0f} s of speech past their greeting: too few for a voiceprint."
    E, secs = np.array(embs), np.array(secs)
    keep = keep_voice(E)
    total = E[keep].sum(axis=0)
    vp = total / np.linalg.norm(total)
    loo = np.array([E[i] @ ((total - E[i]) / np.linalg.norm(total - E[i])) for i in np.flatnonzero(keep)])
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, vector=vp, model=MODEL, model_sha256=MODEL_SHA256, used=int(keep.sum()), dropped=int((~keep).sum()),
             seconds=secs[keep], loo_scores=loo, enrolled=time.strftime("%Y-%m-%d"))
    return (f"Voiceprint saved to {out}: {int(keep.sum())} clips used, {int((~keep).sum())} dropped as another voice. "
            f"Your own clips score {np.percentile(loo, 1):.2f} to {np.median(loo):.2f} against it (1st percentile to median).")


def bar_for(secs: float, bar: float) -> float:
    """The bar for a clip with this much speech. bar is VOICE_MATCH_MIN, the bar from 4 s on: it moves them all together."""
    return bar * float(np.interp(secs, BAR_AT, BAR_SHARE))


def check(clip: np.ndarray, bar: float, skip: int = 0) -> tuple[str, float | None, str]:
    """(verdict, score, the status line) for an int16 clip. `skip`: the samples at its start that hold Jarvis's own voice
    (the greeting, the end of a reply), which are not judged. "other" when the speech scores under the bar for its
    length; "same" otherwise; "unsure" with under MIN_SPEECH of speech, no voiceprint, or the model missing or failing.
    Never raises."""
    path = voiceprint_path()
    try:
        if path is None or not path.is_file():
            return "unsure", None, "Voice match: unsure, no voiceprint on this PC (python voiceprint.py enroll)"
        vp = np.load(path)
        if str(vp["model_sha256"]) != MODEL_SHA256:
            return "unsure", None, "Voice match: unsure, the voiceprint was made with another model (python voiceprint.py enroll)"
        x = speech(clip[skip:])
        secs = len(x) / RATE
        if secs < MIN_SPEECH:
            return "unsure", None, f"Voice match: unsure, only {secs:.1f} s of speech"
        score = float(embed(x) @ vp["vector"])
    except Exception as e:
        return "unsure", None, f"Voice match: unsure, {e}"
    b = bar_for(secs, bar)
    verdict = "other" if score < b else "same"
    return verdict, score, f"Voice match: {verdict}, {score:.2f} against a bar of {b:.2f} for {secs:.1f} s of speech"


def start(clip: np.ndarray, bar: float, skip: int = 0):
    """Starts check() on its own thread, so it runs while the request's text is made. Its .result() is (verdict, score, line)."""
    return EXEC.submit(check, clip, bar, skip)


def selfcheck() -> None:
    """Checks the pure parts: fbank's shape and scale, the outlier drop, and the bars."""
    x = np.sin(np.arange(RATE) * 0.05).astype(np.float32) * 0.3  # one second of a tone
    f = fbank(x)
    assert f.shape == (98, 80) and np.isfinite(f).all() and f.max() < 10, f.shape  # 1 s: 1 + (16000 - 400) // 160 frames
    assert fbank(np.zeros(100, np.float32)).shape == (0, 80)
    rng = np.random.default_rng(0)
    base = rng.normal(size=192)
    base /= np.linalg.norm(base)
    E = np.array([base + 0.05 * rng.normal(size=192) for _ in range(20)] + [rng.normal(size=192)] * 2)
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    keep = drop_outliers(E)
    assert keep[:20].all() and not keep[20:].any(), keep  # the 2 random voices go, the 20 near one voice stay
    # The bars by speech, with VOICE_MATCH_MIN 0.3: 0.05 at half a second, 0.15 at 1 s, 0.25 at 2 s, 0.3 from 4 s.
    for secs, want in [(0.5, 0.05), (1.0, 0.15), (1.5, 0.20), (2.0, 0.25), (4.0, 0.30), (9.0, 0.30)]:
        assert abs(bar_for(secs, 0.3) - want) < 1e-9, (secs, bar_for(secs, 0.3))
    assert abs(bar_for(1.0, 0.2) - 0.1) < 1e-9  # the override moves every bar
    print("ok")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "enroll":
        import listener

        listener.load_env()  # VAD_BOOST: the speech must be picked as the listener picks it
        print(enroll())
    elif arg == "test":
        selfcheck()
    else:
        print(__doc__)
