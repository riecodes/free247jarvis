"""Checks the interruption rules without a mic or a speaker. Run: .venv\\Scripts\\python check_voice.py

  queue  while the user has the floor every line waits, and goes out oldest first once they are done
  play   each sound gets the silence that lets it play to its end
  say    a line that wants an answer opens the follow-up window, prompted or not; an acknowledgment or plain news does not
  call   in a call: the line held unsaid; never a window
  media  what was playing resumes after the line, or after the window when one opens
  hush   the wake word pauses the video and shows the orch's window until the reply; a false wake puts both back at once
  tries  wake word peaks are logged; a near miss ticks, except in a call; the wake word also works mid-task
  look   repeated tries, and each failure the user can't hear, go on screen; nothing else does
  rules  rules.mjs picks say, late or tell, and knows what asks for a held line
  scan   the real WASAPI and media session calls run on this machine (nothing is paused)
  data   only wake word clips are kept, and pruned; words.txt feeds the prompt; a prompt handed back goes nowhere
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import numpy as np

os.environ["VOICE_DATA"] = "off"  # no check clip lands in the real voice data
import listener
import mishears

HERE = Path(__file__).resolve().parent
RATE = listener.CHIME_UP[1]
REAL_OUTPUT_PROBLEM = listener.output_problem


def ears() -> listener.Ears:
    """Ears without its models, with a silent speaker that records what it was told to play."""
    e = listener.Ears.__new__(listener.Ears)
    e.followup, e.deaf_until, e.paused, e.raised, e.reply_by = 100, 0.0, [], None, 0.0
    e.oww, e.vad, e.vad_boost, e.recent = mock.Mock(), mock.Mock(), 1, []
    e.spoke = listener.deque(maxlen=listener.TALK_CHUNKS)
    e.on_chunk, e.voiced = e.wake_chunk, 0
    e.need_name = False  # name_needed tests it; the rest is about what follows the wake word
    e.threshold, e.peak, e.peak_word, e.peak_level, e.next_cue, e.acks, e.words = 0.4, 0.0, "", 0, 0.0, {"jarvis": "ack"}, ["jarvis"]
    e.spoken, e.played, e.queue, e.queue_since, e.last_speech, e.tries = [], [], [], 0.0, 0.0, []
    e.vad.predict = lambda *a, **k: 0.0
    e.speech = lambda text: (e.spoken.append(text), np.zeros(10, np.float32), RATE, "test")[1:]
    e.play = lambda samples, *a, **k: e.played.append(samples) or True
    return e


def tries(scores: list[float], call: bool = False) -> tuple[listener.Ears, list, list]:
    """Feeds these wake word scores in, one per chunk; returns the ears, the events, and the sounds played."""
    events = []
    with mock.patch.object(listener, "in_call", lambda: call), \
            mock.patch.object(listener, "emit", lambda event, **d: events.append((event, d))):
        e = ears()
        for score in scores:
            e.oww.predict = lambda _, s=score: {"jarvis": s}
            e.on_chunk(np.zeros(1280, np.int16))
    return e, events, e.played


def is_sound(played: list, *sounds: tuple) -> bool:
    return len(played) == len(sounds) and all(p is s[0] for p, s in zip(played, sounds))


def pitch(sound: tuple[np.ndarray, int]) -> float:
    spectrum = np.abs(np.fft.rfft(sound[0]))
    return float(np.fft.rfftfreq(len(sound[0]), 1 / sound[1])[spectrum.argmax()])


def run(call: bool, playing: list, **say) -> tuple[listener.Ears, list, list]:
    events, resumed = [], []
    with (mock.patch.object(listener, "in_call", lambda: call)), \
            mock.patch.object(listener, "emit", lambda event, **d: events.append((event, d))), \
            mock.patch.object(listener, "pause_media", lambda: list(playing)), \
            mock.patch.object(listener, "resume_media", resumed.extend), \
            mock.patch.object(listener, "REPLY_WAV", HERE / "tmp" / "check_voice.wav"):
        e = ears()
        e.say("The news.", **say)
    return e, events, resumed


def hush() -> None:
    """From the wake word to the end of the exchange: the video paused, the window up, and both put back once."""
    video = object()
    def wake(playing: list) -> tuple[listener.Ears, list, list]:
        lowered, resumed, left = [], [], list(playing)
        e = ears()
        e.oww.predict = lambda _: {"jarvis": 0.9}
        with mock.patch.object(listener, "pause_media", lambda: [left.pop() for _ in list(left)]), \
                mock.patch.object(listener, "raise_orch", lambda: ("window", True)), \
                mock.patch.object(listener, "lower_orch", lowered.append), \
                mock.patch.object(listener, "resume_media", resumed.extend), \
                mock.patch.object(listener, "REPLY_WAV", HERE / "tmp" / "check_voice.wav"):
            e.on_chunk(np.zeros(1280, np.int16))
            assert e.paused == playing and e.raised == (("window", True) if playing else None)
            yield e, lowered, resumed

    both = [("window", True)], [video]
    with mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "emit"):
        # A false wake, nobody spoke: back at once.
        for e, lowered, resumed in wake([video]):
            e.request_done(None)
            assert (lowered, resumed) == both and not e.paused and not e.raised and not e.reply_by
        # Only the wake word was said, or noise: the same.
        for e, lowered, resumed in wake([video]):
            with mock.patch.object(listener, "transcribe", lambda clip: "Jarvis"):
                e.request_done(np.zeros(1, np.int16))
            assert (lowered, resumed) == both
        # A request: paused through the wait, and through news that isn't the reply; put back once when the reply ends.
        for e, lowered, resumed in wake([video]):
            with mock.patch.object(listener, "transcribe", lambda clip: "open notepad"):
                e.request_done(np.zeros(1, np.int16))
            assert not lowered and not resumed and e.reply_by
            e.flush()
            assert not lowered and not resumed
            e.say("Other news.", asked=False, hold=True)
            assert not lowered and not resumed
            e.say("Done.", window=False)
            assert (lowered, resumed) == both
            e.flush()
            assert (lowered, resumed) == both
        # A reply with a question: still paused in the window; put back when it closes.
        for e, lowered, resumed in wake([video]):
            with mock.patch.object(listener, "transcribe", lambda clip: "open notepad"):
                e.request_done(np.zeros(1, np.int16))
            e.say("Which one?")
            assert e.on_chunk == e.record_chunk and not lowered and not resumed
            e.close()
            assert (lowered, resumed) == both
        # No reply at all: not paused forever. Not while the user is talking, though.
        for e, lowered, resumed in wake([video]):
            with mock.patch.object(listener, "transcribe", lambda clip: "open notepad"):
                e.request_done(np.zeros(1, np.int16))
            e.reply_by = listener.time.monotonic() - 1
            e.record(e.request_done)
            e.flush()
            assert not lowered and not resumed
            e.on_chunk = e.wake_chunk
            e.flush()
            assert (lowered, resumed) == both and not e.reply_by
        # Nothing was playing (or the user paused it): no window, and nothing to put back.
        for e, lowered, resumed in wake([]):
            e.request_done(None)
            assert not lowered and not resumed


def looking() -> None:
    """The on-screen caption: repeated tries that got nowhere, a stray near miss, and each failure the user can't hear."""
    near_twice = [0.3, 0.0, 0.3, 0.0]
    with mock.patch.object(listener, "media_playing", lambda: False):
        captions = lambda r: [d for ev, d in r[1] if ev == "caption"]
        # Once is not looking; twice is, with the generic hint since nothing is detectably wrong.
        assert not captions(tries([0.3, 0.0]))
        shown = captions(tries(near_twice))
        assert len(shown) == 1 and shown[0]["looking"] and listener.CANT_HEAR in shown[0]["text"]
        # A near miss in a call stays quiet, as does one with a video playing.
        assert not captions(tries(near_twice, call=True))
    with mock.patch.object(listener, "media_playing", lambda: True):
        assert not captions(tries(near_twice))
    # Two tries spread out are not looking.
    with mock.patch.object(listener, "media_playing", lambda: False), mock.patch.object(listener, "emit") as emitted, \
            mock.patch.object(listener, "in_call", lambda: False):
        e = ears()
        e.tried()
        e.tries = [t - listener.LOOK_WINDOW for t in e.tries]
        e.tried()
        assert not emitted.called
        # "Jarvis, Jarvis" twice leaves no words: looking. A real request clears the count.
        e = ears()
        with mock.patch.object(listener, "transcribe", lambda clip: "Jarvis, Jarvis"):
            e.request_done(np.zeros(1, np.int16))
            e.request_done(np.zeros(1, np.int16))
        assert any(c.args[0] == "caption" for c in emitted.call_args_list)
        e = ears()
        e.tried()
        with mock.patch.object(listener, "transcribe", lambda clip: "open notepad"):
            e.request_done(np.zeros(1, np.int16))
        assert e.tries == []

    # A muted PC: the line goes on screen, word for word. Failed sound or voice: the same.
    with mock.patch.object(listener, "output_problem", lambda: "Your PC's sound is muted."):
        _, events, _ = run(False, [], asked=False)
    assert ("caption", {"text": "Your PC's sound is muted. I said: The news."}) in events
    _, events, _ = run(False, [], asked=False)
    assert not [ev for ev in events if ev[0] == "caption"]  # all fine: never a caption per line
    # A line nobody prompted that needs them: a notification, but never in a call, where a client could see it.
    _, events, _ = run(False, [], hold=True)
    assert ("caption", {"text": "The news.", "remind": True}) in events
    _, events, _ = run(True, [], hold=True)
    assert not [ev for ev in events if ev[0] == "caption"]
    _, events, _ = run(False, [])
    assert not [ev for ev in events if ev[0] == "caption"]  # a reply they just asked for: the window has it
    events = []
    with mock.patch.object(listener, "emit", lambda event, **d: events.append((event, d))):
        e = ears()
        e.line("The news.", asked=False)
        e.say = mock.Mock(side_effect=OSError("no voice"))
        e.flush()
    assert ("caption", {"text": "My voice failed, so in words: The news."}) in events

    # What Windows can tell about the speaker.
    def problem(mute=0, level=0.5, name="Speakers (Realtek(R) Audio)", device=True):
        speakers = mock.Mock(FriendlyName=name)
        speakers.EndpointVolume.GetMute.return_value = mute
        speakers.EndpointVolume.GetMasterVolumeLevelScalar.return_value = level
        with mock.patch("pycaw.pycaw.AudioUtilities.GetSpeakers", return_value=speakers, side_effect=None if device else OSError()), \
                mock.patch("sounddevice.query_devices", return_value={"name": "Speakers (Realtek(R) Audio)"}):
            return REAL_OUTPUT_PROBLEM()

    assert problem() == ""
    assert "muted" in problem(mute=1) and "zero" in problem(level=0.0) and "no speaker" in problem(device=False)
    assert "switched" in problem(name="Headphones (WH-1000XM4)")


def mic_names() -> None:
    """The window names the device the stream has open."""
    with mock.patch("sounddevice.query_devices", side_effect={4: {"name": "Mic A"}}.__getitem__), mock.patch.object(listener, "emit", lambda *a, **k: None):
        assert listener.mic_name(mock.Mock(device=4)) == "Mic A"
        assert listener.mic_name(mock.Mock(device=99)) == ""  # gone: says so, and the voice goes on


def staying_quiet() -> None:
    """A call or talk around: a stricter wake word, no unasked line, no window."""
    chunk = np.ones(listener.CHUNK, np.int16)

    def wake(e, score, said="Hey Jarvis, open notepad", call=False):
        events = []
        with mock.patch.object(listener, "in_call", lambda: call), mock.patch.object(listener, "emit", lambda ev, **d: events.append((ev, d))), \
                mock.patch.object(listener, "transcribe", lambda clip: said), mock.patch.object(listener, "pause_media", list), mock.patch.object(listener, "media_playing", lambda: False):
            e.oww.predict = lambda _: {"jarvis": score}
            e.on_chunk(chunk)
            if e.on_chunk != e.wake_chunk:
                e.on_chunk = e.record_chunk
                e.vad.predict = lambda *a, **k: 0.9
                for _ in range(listener.MIN_VOICED):
                    e.on_chunk(chunk)
                e.vad.predict = lambda *a, **k: 0.0
                for _ in range(listener.END_QUIET):
                    e.on_chunk(chunk)
        return events

    # The signals: an app on the mic comes first and names itself; titles only match a meeting's window.
    with mock.patch.object(listener, "mic_holder", lambda: "chrome on the mic"), mock.patch.object(listener, "call_window", lambda: "a Meet window"):
        assert listener.in_call() and listener.call_why == "chrome on the mic"
    with mock.patch.object(listener, "mic_holder", lambda: ""), mock.patch.object(listener, "call_window", lambda: "a Meet window"):
        assert listener.in_call() and listener.call_why == "a Meet window"
    with mock.patch.object(listener, "mic_holder", lambda: ""), mock.patch.object(listener, "call_window", lambda: ""):
        assert not listener.in_call() and listener.call_why == ""
    match = lambda title: [app for app, p in listener.CALL_TITLES.items() if listener.re.search(p, title)]
    assert match("Meet - abc-defg-hij - Google Chrome") == ["Meet"] and match("Zoom Meeting") == ["Zoom"]
    assert match("Weekly sync | Meeting | Microsoft Teams") == ["Teams"]
    for other in ("Meeting notes - Google Docs", "How to meet people - YouTube", "Zoom out - Figma", "Microsoft Teams"):
        assert not match(other), other

    heard = lambda ev: [d["text"] for k, d in ev if k == "heard"]
    # Alone, with the same weak score: wakes as before.
    assert heard(wake(ears(), 0.45, "open notepad")) == ["open notepad"]
    # In a call: too weak; strong.
    e = ears()
    assert wake(e, 0.45, call=True) and e.on_chunk == e.wake_chunk
    assert heard(wake(ears(), 0.95, call=True)) == ["open notepad"]

    # People talking, with no call: the same, then the state goes to the window, and a real request clears it.
    e = ears()
    e.spoke.extend([True] * 100 + [False] * 100)
    assert e.talking()
    events = []
    with mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "emit", lambda ev, **d: events.append((ev, d))):
        e.oww.predict = lambda _: {"jarvis": 0.0}
        e.wake_chunk(chunk)
    assert ("quiet", {"on": True, "text": "people talking"}) in events and e.on_chunk == e.wake_chunk
    assert heard(wake(e, 0.95)) == ["open notepad"] and not e.talking() and not e.spoke
    quiet_room = ears()
    quiet_room.spoke.extend([True] * 124)
    assert not quiet_room.talking()  # too little to tell
    quiet_room.spoke.extend([False] * 300)
    assert not quiet_room.talking()

    # Staying quiet, a line nobody asked for waits unsaid, and a reply they asked for opens no window.
    e = ears()
    e.spoke.extend([True] * 200)
    events = []
    with mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "emit", lambda ev, **d: events.append((ev, d))), \
            mock.patch("soundfile.write"), mock.patch.object(listener.os, "replace"), mock.patch.object(listener, "output_problem", lambda: ""), \
            mock.patch.object(listener, "pause_media", list):
        e.say("News?", hold=True)
        assert e.spoken == [] and ("held", {"text": "News?"}) in events and not [x for x in events if x[0] == "caption"]
        e.say("Your answer?")
        assert e.spoken == ["Your answer?"] and ("spoken", {"listening": False}) in events and e.on_chunk == e.wake_chunk

    # A listening window that runs on is thrown away unsent, and a wake word's request isn't capped.
    e = ears()
    e.vad.predict = lambda *a, **k: 0.9
    sent = []
    with mock.patch.object(listener, "emit", lambda *a, **k: None), mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "pause_media", list):
        e.record(sent.append, give_up=100)
        for _ in range(listener.SHORT_CLIP):
            e.on_chunk(chunk)
        assert not sent and e.on_chunk == e.wake_chunk and e.talking()
        e = ears()
        e.vad.predict = lambda *a, **k: 0.9
        e.woke = (0.9, 9)
        e.record(sent.append)
        for _ in range(listener.SHORT_CLIP + 1):
            e.record_chunk(chunk)
        assert e.on_chunk == e.record_chunk and e.cap == listener.MAX_CLIP


def name_needed() -> None:
    """"Hey Jarvis" or "Jarvis" wakes it. A fired score with any other words does nothing the user can notice."""
    chunk = np.ones(listener.CHUNK, np.int16)

    def fire(said, score=0.5, call=False, voice_data="", tmp=""):
        e, events, windows = ears(), [], []
        e.need_name = True
        e.spoke.extend([True] * 200 if call else [])
        e.oww.predict = lambda _: {"jarvis": score}
        e.recent = listener.deque(maxlen=listener.NAME_ROLL)

        def stt(clip, timeout=600):
            assert timeout == listener.NAME_TIMEOUT and len(clip) == listener.CHUNK
            if isinstance(said, Exception):
                raise said
            return said

        with mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "transcribe", stt), \
                mock.patch.object(listener, "emit", lambda ev, **d: events.append(ev)), \
                mock.patch.object(listener, "pause_media", lambda: windows.append(1) or []), \
                mock.patch.dict(listener.os.environ, {"VOICE_DATA": voice_data, "LOCALAPPDATA": tmp or listener.os.environ["LOCALAPPDATA"]}):
            e.on_chunk(chunk)
        return e, events, windows

    for said in ("Hey Jarvis", "Jarvis.", "Hey Jarvis, status", "A Jarvis status", "hey jervis"):
        e, events, windows = fire(said)
        assert "wake" in events and e.on_chunk == e.after_wake and is_sound(e.played, listener.CHIME_UP) and windows, said
    for said in ("Hey.", "Hey", "", "Hey Travis.", "Hey there.", "Hey Claude", "jarvisize"):
        e, events, windows = fire(said)
        assert "wake" not in events and e.on_chunk == e.wake_chunk and not e.played and not windows, said
        assert e.woke is None and "peak" in events and "heard" not in events and e.tries, said
    # Speech to text down: it wakes rather than lose the request, and says why in the log.
    e, events, _ = fire(RuntimeError("offline"))
    assert "wake" in events and "status" in events
    # A try it ignored is kept only by choice, for tuning, and not while the user is with someone.
    with tempfile.TemporaryDirectory() as tmp:
        rows = Path(tmp) / "free247jarvis" / "voicedata" / "requests.jsonl"
        fire("Hey.", voice_data="off", tmp=tmp)
        assert not rows.exists()
        fire("Hey.", score=0.9, call=True, voice_data="on", tmp=tmp)
        assert not rows.exists()
        fire("Hey.", voice_data="on", tmp=tmp)
        row = json.loads(rows.read_text(encoding="utf-8"))
        assert row["transcript"] == "Hey." and not row["kept"] and row["wake_score"] == 0.5
    # The request's clip starts as before: the 1.5 s for the check stays out of it, so what came before the name isn't sent on.
    e = ears()
    e.recent = [chunk] * 10
    e.oww.predict = lambda _: {"jarvis": 0.9}
    with mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "emit"), mock.patch.object(listener, "pause_media", list):
        e.on_chunk(chunk)
    assert len(e.clip) == listener.PRE_ROLL


def voice_data() -> None:
    """Only wake word clips are kept, only by choice, in no synced folder, not in a call; old ones go unless forever."""
    real = Path(listener.os.environ["LOCALAPPDATA"]) / "free247jarvis" / "voicedata"
    assert HERE.parent not in real.parents, real
    clip = np.ones(listener.RATE, np.int16)

    def asked(e, said="open notepad", call=False, choice="on"):
        with mock.patch.object(listener, "transcribe", lambda clip: said), mock.patch.object(listener, "in_call", lambda: call), \
                mock.patch.dict(listener.os.environ, {"VOICE_DATA": choice}), mock.patch.object(listener, "emit", lambda *a, **k: None):
            e.request_done(clip)

    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(listener.os.environ, {"LOCALAPPDATA": tmp}):
        folder = Path(tmp) / "free247jarvis" / "voicedata"
        rows = lambda: [json.loads(line) for line in (folder / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
        e = ears()
        asked(e)  # a follow-up window's clip: no wake word
        for choice in ("off", ""):  # nobody chose: nothing is kept
            e.woke = (0.5, 9)
            asked(e, choice=choice)
        e.woke = (0.5, 9)
        asked(e, call=True)
        assert not folder.exists()
        time.sleep(0.002)
        e.woke = (0.91, 120)
        asked(e, "Hey Jarvis, open notepad")
        assert e.woke is None
        asked(e)  # the next one is a follow-up again
        assert [r["wake_score"] for r in rows()] == [0.91] and rows()[0]["kept"], rows()
        assert rows()[0]["transcript"] == "Hey Jarvis, open notepad" and (folder / rows()[0]["clip"]).is_file()

        # A failure to save never costs the request.
        heard = []
        with mock.patch.object(listener, "wav_bytes", side_effect=OSError("full")), mock.patch.object(listener, "transcribe", lambda clip: "open notepad"), \
                mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "emit", lambda ev, **d: heard.append(ev)), \
                mock.patch.dict(listener.os.environ, {"VOICE_DATA": "on"}):
            e.woke = (0.5, 9)
            e.request_done(clip)
        assert "heard" in heard and "status" in heard, heard

        # forever keeps a clip past both limits, and it is saved like any other.
        old = folder / rows()[0]["clip"]
        listener.os.utime(old, (1, 1))
        with mock.patch.dict(listener.os.environ, {"VOICE_DATA": "forever"}), mock.patch.object(listener, "DATA_MAX", 0):
            listener.prune_data()
        assert old.exists() and len(rows()) == 1
        time.sleep(0.002)
        e.woke = (0.5, 9)
        asked(e, choice="forever")
        assert len(rows()) == 2 and old.exists()
        (folder / rows()[1]["clip"]).unlink()
        (folder / "requests.jsonl").write_text(json.dumps(rows()[0]) + "\n", encoding="utf-8")

        # Past DATA_DAYS or over DATA_MAX, clip and row both go.
        listener.prune_data()
        assert not old.exists() and rows() == []
        for name in ("1.wav", "2.wav"):
            (folder / name).write_bytes(b"x" * 10)
        with mock.patch.object(listener, "DATA_MAX", 15):
            listener.prune_data()
        assert [c.name for c in folder.glob("*.wav")] == ["2.wav"]

        # The prompt: words.txt adds to the base without repeats, and never passes Groq's limit, which fails the request.
        words = Path(tmp) / "words.txt"
        words.write_text("# note\nclaude\nVercel  # a note\n\n" + "\n".join(f"word{i:04d}" for i in range(400)), encoding="utf-8")
        terms = listener.load_terms(words)
        assert terms[:len(listener.BASE_TERMS) + 1] == listener.BASE_TERMS + ["Vercel"] and len(", ".join(terms)) + 1 <= listener.PROMPT_MAX
        assert len(terms) < 400 and listener.load_terms(Path(tmp) / "none.txt") == listener.BASE_TERMS

    # Whisper hearing a request again in the quiet after it, one segment on. Only the neighbour goes, and shaky ones still drop.
    seg = lambda *texts: {"segments": [{"text": t, "avg_logprob": -0.3} for t in texts]}
    assert listener.segments_text(seg(" Open it.", " Open it.")) == "Open it."
    assert listener.segments_text(seg("Yes.", "Open it.", "Yes.")) == "Yes. Open it. Yes."
    assert listener.segments_text({"segments": [{"text": "Open it.", "avg_logprob": -0.3}, {"text": "Noise.", "avg_logprob": -9}]}) == "Open it."

    # Whisper's prompt handed back on noise (from real answers, 2026-11-01), and what must still pass.
    for back in ["Rc, Cpd, Su, Toc, Cpd, Su, Toc", "Riecodes, wrc, crc, cpc, cpc.", "Cpd, co, ManyChat, Nakeem.", "Cpd."]:
        with mock.patch.object(listener, "emit", lambda *a, **k: heard.append(a[0])):
            heard.clear()
            with mock.patch.object(listener, "transcribe", lambda clip: back), mock.patch.object(listener, "in_call", lambda: False):
                ears().request_done(clip)
        assert "heard" not in heard, back
    for real_one in ["A, B, C", "yes, go on", "deploy to Vercel, then tell me", "cpd na yung riecodes"]:
        assert not listener.handed_back(real_one), real_one

    found = mishears.near_terms([{"kept": True, "transcript": "open versal, name cheap, and my sessions"},
                                 {"kept": False, "transcript": "versal"}], ["Vercel", "Namecheap", "session"])
    assert found == {("versal", "Vercel"): 1, ("name cheap", "Namecheap"): 1}, found
    assert mishears.shaky([{"clip": "a.wav", "segments": [{"text": " huh", "avg_logprob": -0.9}, {"text": "ok", "avg_logprob": -0.1}]}]) == [(-0.9, "a.wav", "huh")]


def main() -> None:
    video = object()
    listener.output_problem = lambda: ""  # this machine's real speaker must not decide the checks
    # Nor may the checks touch this machine's real video or orch window.
    listener.pause_media, listener.resume_media = lambda: [], lambda sessions: None
    listener.raise_orch, listener.lower_orch = lambda: None, lambda raised: None
    looking()
    hush()

    # Only "Hey Jarvis" wakes it, and "Claude" in a request is the user's word, not a wake word to strip.
    assert listener.wake_words() == ["hey_jarvis"]
    assert listener.strip_wake("Hey Jarvis, status") == "status"
    assert listener.strip_wake("Claude Code is slow") == "Claude Code is slow"
    assert listener.strip_wake("Hey Claude is what I said") == "Hey Claude is what I said"

    # A reply: in full, then the window, with the video still paused until the window ends.
    e, events, resumed = run(False, [video])
    assert e.on_chunk == e.record_chunk and e.spoken == ["The news."]
    assert not resumed and e.paused == [video]
    # Nobody asked: in full, no window, the video back at once.
    e, events, resumed = run(False, [video], asked=False, hold=True)
    assert e.on_chunk == e.wake_chunk and e.spoken == ["The news."] and resumed == [video]
    # A reply that ends the exchange: in full, no window, the video back at once.
    e, events, resumed = run(False, [video], window=False)
    assert e.on_chunk == e.wake_chunk and e.spoken == ["The news."] and resumed == [video]
    # Nothing was playing: nothing resumes.
    assert run(False, [], asked=False)[2] == []

    # A call: the line held, unsaid, no window, and nothing paused.
    e, events, resumed = run(True, [video], asked=False, hold=True)
    assert e.spoken == [] and ("held", {"text": "The news."}) in events
    assert e.on_chunk == e.wake_chunk and not e.paused
    # In a call the user asked: in full, but still no window.
    e, _, _ = run(True, [], asked=True)
    assert e.spoken == ["The news."] and e.on_chunk == e.wake_chunk
    # An older request in a call waits like any other line.
    e, events, _ = run(True, [], asked=True, hold=True)
    assert e.spoken == [] and events[0][0] == "held"

    # Never over the user: while a request or an answer is being recorded every line waits, oldest first.
    events = []
    with mock.patch.object(listener, "in_call", lambda: False), \
            mock.patch.object(listener, "emit", lambda event, **d: events.append((event, d))), \
            mock.patch.object(listener, "pause_media", lambda: []), \
            mock.patch.object(listener, "REPLY_WAV", HERE / "tmp" / "check_voice.wav"):
        e = ears()
        e.on_chunk, e.clip, e.voiced = e.record_chunk, ["their words"], 5
        e.line("First.", asked=False, hold=True)
        e.line("Second?", hold=True)
        e.flush()
        assert e.spoken == [] and e.on_chunk == e.record_chunk and e.clip == ["their words"]
        assert [d["text"] for ev, d in events if ev == "queued"] == ["First.", "Second?"]
        # Their words are handled: the oldest line goes out. The second opens the window.
        e.wait_for_wake()
        e.flush()
        assert e.spoken == ["First."] and e.on_chunk == e.wake_chunk
        e.flush()
        assert e.spoken == ["First.", "Second?"] and e.on_chunk == e.record_chunk
        # That open window holds the next line too, even before the user says a word, until it closes.
        e.voiced = 0
        e.line("Third.", asked=False, hold=True)
        e.flush()
        assert e.spoken == ["First.", "Second?"]
        e.close()
        e.flush()
        assert e.spoken[-1] == "Third."
        # Speech with no recording on: the line waits for 3 s of quiet, but not forever. Quiet: it goes at once.
        e = ears()
        e.line("News.", asked=False, hold=True)
        e.flush()
        assert e.spoken == ["News."]
        e.last_speech = listener.time.monotonic()
        e.line("News.", asked=False, hold=True)
        e.flush()
        assert e.spoken == ["News."]
        e.queue_since -= listener.HOLD_MAX
        e.flush()
        assert e.spoken == ["News.", "News."]
        # The VAD feeds that, while waiting for the wake word.
        e = ears()
        e.vad.predict = lambda *a, **k: 0.9
        e.oww.predict = lambda _: {"jarvis": 0.0}
        e.on_chunk(np.zeros(1280, np.int16))
        assert e.last_speech > 0

    # The whole sound plays: silence is added after it, since the stream closes before its last buffers have played.
    tone = np.ones(100, np.float32)
    with mock.patch("sounddevice.play") as played, mock.patch("sounddevice.wait"):
        e = ears()
        listener.Ears.play(e, tone, 1000)
        assert len(played.call_args[0][0]) == 100 + int(1000 * listener.DRAIN)
        assert listener.DRAIN >= 0.3  # measured on the speaker: about 0.28 s between wait() returning and the end
        listener.Ears.play(e, tone, 1000, drain=False)
        assert len(played.call_args[0][0]) == 100

    # A question with nobody talking and no call: in full, with the window. In a call: held, no window.
    e, _, _ = run(False, [], hold=True)
    assert e.spoken == ["The news."] and e.on_chunk == e.record_chunk
    e, events, _ = run(True, [], hold=True)
    assert e.spoken == [] and e.on_chunk == e.wake_chunk and events[0][0] == "held"

    # A near miss: its peak is logged and it ticks once the try is over, not while the score still climbs.
    e, events, played = tries([0.0, 0.3, 0.35])
    assert played == [] and not [ev for ev in events if ev[0] == "peak"]
    e, events, played = tries([0.0, 0.3, 0.35, 0.0])
    assert ("peak", {"word": "jarvis", "score": 0.35, "level": 0}) in events and is_sound(played, listener.CHIME_NEAR)
    # Too low for a tick, but in the log. Noise stays out of it.
    e, events, played = tries([0.1, 0.0])
    assert events == [("peak", {"word": "jarvis", "score": 0.1, "level": 0})] and played == []
    assert tries([0.0, 0.02, 0.0])[1] == []
    # Two near misses in a row: one tick.
    assert is_sound(tries([0.3, 0.0, 0.3, 0.0])[2], listener.CHIME_NEAR)
    # The wake word: the pop and recording, as before, with its score in the log.
    e, events, played = tries([0.5])
    assert [ev[0] for ev in events] == ["peak", "wake"] and is_sound(played, listener.CHIME_UP)
    assert e.on_chunk == e.after_wake
    # Right after a request, while the boss works on it: the same pop and recording, and its reply waits in the queue.
    with mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "emit"), \
            mock.patch.object(listener, "transcribe", lambda clip: "open notepad"):
        e = ears()
        e.request_done(np.zeros(1, np.int16))
        e.played.clear()
        e.oww.predict = lambda _: {"jarvis": 0.9}
        e.on_chunk(np.zeros(1280, np.int16))
        assert is_sound(e.played, listener.CHIME_UP) and e.on_chunk == e.after_wake
        e.line("The answer.")
        e.flush()
        assert e.spoken == [] and e.queue
    # In a call the tick stays silent, and the score still reaches the log.
    assert tries([0.3, 0.0], call=True)[2] == []
    assert [ev for ev in tries([0.3, 0.0], call=True)[1] if ev[0] != "quiet"][0][0] == "peak"

    # The tick against the three sounds the user knows.
    known = [pitch(s) for s in (listener.CHIME_UP, listener.CHIME_DOWN, listener.CHIME_CLOSE)]
    assert pitch(listener.CHIME_NEAR) > 1.5 * max(known), known

    subprocess.run(["node", "--input-type=module", "-e", """
        import assert from 'node:assert'
        import { asksForHeld as a, asksSomething as q, isAnswer as n, isLong as l, isLooking as k, verbFor as v } from './rules.mjs'
        for (const t of ['Hello?', 'Hello, hello.', 'Hi Jarvis', 'Are you there?', 'Hello? Are you there, Jarvis?',
          'Can you hear me?', 'Andyan ka ba?', 'Jarvis, are you still there?'])
          assert(k(t), t)
        for (const t of ['Hello, how do I fix the navbar?', 'Tell the course session it can go on now.', 'Okay, ship it.',
          'Hi, so I want to implement a fallback for when you do not hear me at all.'])
          assert(!k(t), t)
        for (const t of ['Q8 A', 'q8a', 'p1 b.', 'P 1, B', 'B.', 'b', '3', 'B. Okay. Hello?',
          'Alright, A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q, R, S, C, U, V, W, X, Y, and Z.', 'A, B, C, D.'])
          assert(n(t), t)
        for (const t of ['A joke please.', 'I think so.', "What's up?", 'Hey there', 'thank you very much'])
          assert(!n(t), t)
        assert(l('let us try first if you would recognize each and every letter'))
        assert(!l('um the what') && !l('Hello?'))
        assert.equal(v(0, true, 1e9), 'late')
        assert.equal(v(0, false, 1e9), 'tell')
        assert.equal(v(1e9 - 10_000, true, 1e9), 'say')
        assert.equal(v(1e9 - 10_000, false, 1e9), 'end')
        assert.equal(v(1e9 - 300_000, true, 1e9), 'late')
        assert.equal(v(1e9 - 300_000, false, 1e9), 'tell')
        for (const t of ['Sir, restart now?', 'Sir, say A for on, or B to keep it off.', 'Pick one in the terminal.'])
          assert(q(t), t)
        for (const t of ['Sir, understood.', 'Sir, okay, no restart.', 'Sir, turning email on now.'])
          assert(!q(t), t)
        for (const t of ["What's the update?", 'Ano yung balita?', 'Go ahead.', 'Ano yun?', 'Tell me the message.'])
          assert(a(t), t)
        for (const t of ['Update the README please.', 'Yes.', "What's the update on the dentaria deploy today please?"])
          assert(!a(t), t)
    """], cwd=HERE, check=True)

    assert listener.in_call() in (True, False)
    errors = []
    with mock.patch.object(listener, "emit", lambda event, **d: errors.append(d)):
        listener.in_call()
    assert not errors, errors

    e = ears()
    e.vad_boost, seen = 16, []
    e.vad.predict = lambda chunk, **k: seen.append(chunk) or 0.9
    chunk = np.array([100, -3000], dtype=np.int16)
    assert e.is_speech(chunk) and seen[0].tolist() == [1600, -32768] and chunk.tolist() == [100, -3000]

    # A MIC_DEVICE that won't open falls back to Windows' default and says so; if the default fails too, it raises.
    def stream(device, **_):
        if device is not None:
            raise OSError("Sample format not supported")
        return mock.Mock()
    statuses = []
    with mock.patch.object(listener, "mic_device", return_value=18), mock.patch("sounddevice.InputStream", side_effect=stream), \
            mock.patch.object(listener, "emit", lambda event, **d: statuses.append((event, d))):
        listener.open_mic(listener.queue.Queue())
    assert statuses and statuses[-1][0] == "status" and "Windows" in statuses[-1][1]["text"], statuses
    with mock.patch.object(listener, "mic_device", return_value=None), mock.patch("sounddevice.InputStream", side_effect=OSError("no mic")):
        try:
            listener.open_mic(listener.queue.Queue())
            raise AssertionError("open_mic should raise when the default fails too")
        except OSError:
            pass

    # MIC_FALLBACK comes before Windows' default, whether MIC_DEVICE won't open or goes silent later.
    inputs = [{"name": "Microphone (Voicemod)", "max_input_channels": 2}, {"name": "Speakers", "max_input_channels": 0},
              {"name": "Microphone (Realtek)", "max_input_channels": 2}]
    opened = []

    def stream2(device, **_):
        opened.append(device)
        if device == 0:
            raise OSError("won't open")
        return mock.Mock()
    with mock.patch.dict(listener.os.environ, {"MIC_DEVICE": "voicemod", "MIC_FALLBACK": "Realtek"}), \
            mock.patch("sounddevice.query_devices", return_value=inputs), mock.patch("sounddevice.InputStream", side_effect=stream2), \
            mock.patch.object(listener, "emit", lambda *a, **k: None):
        assert listener.mic_device() == 0 and listener.mic_device("") is None
        listener.open_mic(listener.queue.Queue())
        assert opened == [0, 2], opened
        opened.clear()
        old = mock.Mock()
        assert listener.spare_mic(old, listener.queue.Queue()) and opened == [2] and old.close.called
    with mock.patch.dict(listener.os.environ, {"MIC_FALLBACK": ""}):  # no spare: the old mic stays, and the warning goes on
        old = mock.Mock()
        assert listener.spare_mic(old, listener.queue.Queue()) is None and not old.close.called

    # Live words start at the first speech with the pre-roll, only with the window open, never in voice training,
    # and stop before the request's own text is asked for.
    class Live:
        def __init__(self):
            self.got, self.stopped = [], False

        def feed(self, chunk):
            self.got.append(chunk)

        def stop(self):
            self.stopped = True

    speech = np.ones(listener.CHUNK, np.int16)
    live = Live()
    with mock.patch.object(listener, "live_words", return_value=live) as start:
        e = ears()
        e.vad_boost, e.watching, done = 1, True, []
        e.vad.predict = lambda *a, **k: 0.9 if e.talking else 0.0
        e.talking = False
        e.record(done.append, [speech])
        e.record_chunk(speech)
        assert not start.called  # a false wake pays for nothing
        e.talking = True
        for _ in range(3):
            e.record_chunk(speech)
        assert start.call_count == 1 and len(live.got) == 5 and e.live is live
        e.talking = False
        for _ in range(listener.END_QUIET):
            e.record_chunk(speech)
        assert done and live.stopped and e.live is None
        start.reset_mock()
        e = ears()  # the window closed
        e.vad_boost, e.watching = 1, False
        e.vad.predict = lambda *a, **k: 0.9
        e.record(done.append)
        e.record_chunk(speech)
        assert not start.called
        e = ears()  # voice training stays on this PC
        e.vad_boost, e.watching = 1, True
        e.vad.predict = lambda *a, **k: 0.9
        e.record(e.take_done)
        e.record_chunk(speech)
        assert not start.called

    # Groq's live words: one request at a time, every LIVE_EVERY chunks, shown without the wake word; a failure says so.
    calls, shown, go = [], [], listener.threading.Event()

    def groq(clip, timeout):
        calls.append(len(clip))
        go.wait(5)
        return "Hey Jarvis, open terminal two"
    with mock.patch.object(listener, "groq_text", groq), mock.patch.object(listener, "emit", lambda ev, **d: shown.append((ev, d))):
        g = listener.GroqLive()
        for _ in range(listener.LIVE_EVERY * 3):
            g.feed(speech)
        assert len(calls) == 1 and calls[0] == listener.LIVE_EVERY * listener.CHUNK and g.busy
        go.set()
        for _ in range(100):
            if not g.busy:
                break
            time.sleep(0.01)
        assert shown == [("partial", {"text": "open terminal two"})], shown
    voice_data()
    name_needed()
    mic_names()
    staying_quiet()
    print("ok")


if __name__ == "__main__":
    sys.exit(main())
