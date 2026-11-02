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
    e.closing_gap = 0  # closing_cut tests it
    e.listen_all = False  # listen_after tests it
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


def listen_after() -> None:
    """It listens after every line it says, a status answer or news as well as a question: never in a call or room talk,
    with the mic closed, or with the window off."""
    def say(asked=True, hold=False, window=True, call=False, talking=False, mic_open=True, followup=100, every=True):
        e, events = ears(), []
        e.listen_all, e.mic_open, e.followup = every, mic_open, followup
        if talking:
            e.spoke.extend([True] * 200)
        with mock.patch.object(listener, "in_call", lambda: call), mock.patch.object(listener, "emit", lambda ev, **d: events.append((ev, d))), \
                mock.patch("soundfile.write"), mock.patch.object(listener.os, "replace"), mock.patch.object(listener, "output_problem", lambda: ""), \
                mock.patch.object(listener, "pause_media", list), mock.patch.object(listener, "resume_media"):
            e.say("Three sessions are working.", asked=asked, hold=hold, window=window)
        return ("spoken", {"listening": True}) in events and e.on_chunk == e.record_chunk, events

    assert say(window=False)[0]  # the router's status answer, the "end" verb
    assert say()[0]  # a question
    assert say(asked=False, hold=True)[0]  # news
    assert not say(window=False, call=True)[0]
    assert not say(window=False, talking=True)[0]
    assert not say(asked=False, hold=False, mic_open=False)[0]
    assert not say(window=False, followup=0)[0]
    # News with no question doesn't turn into a notification for it.
    assert not [d for ev, d in say(asked=False, hold=True)[1] if d.get("remind")]
    assert [d for ev, d in say(asked=True, hold=True)[1] if d.get("remind")]
    # News goes out over a window that followed a plain line with nobody speaking; speech or a question holds it.
    e = ears()
    e.listen_all = True
    with mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "emit"), \
            mock.patch("soundfile.write"), mock.patch.object(listener.os, "replace"), mock.patch.object(listener, "output_problem", lambda: ""), \
            mock.patch.object(listener, "pause_media", list), mock.patch.object(listener, "resume_media"):
        e.say("Three sessions are working.", window=False)
        assert e.on_chunk == e.record_chunk and e.idle_window and not e.user_turn()
        e.voiced = 1
        assert e.user_turn()
        e.voiced = 0
        e.say("Which one?")
        assert e.on_chunk == e.record_chunk and not e.idle_window and e.user_turn()
    # LISTEN_AFTER=asked: as it was.
    assert not say(window=False, every=False)[0] and say(every=False)[0]


def settings() -> None:
    """The window's switches reach the running listener, and off means off."""
    with mock.patch.dict(listener.os.environ, {"SOUNDS": "off", "GREETING": "off", "LISTEN_AFTER": "asked", "FOLLOWUP_SECONDS": "20", "CLOSING_CUT": "off"}):
        e = ears()
        e.greetings = [("Yes, sir.", np.ones(10, np.float32), RATE)]
        e.read_settings()
        assert not e.sounds and not e.greetings and not e.listen_all and e.followup == 250 and e.closing_gap == 0
    with mock.patch.dict(listener.os.environ, {"SOUNDS": "", "GREETING": "", "LISTEN_AFTER": "", "FOLLOWUP_SECONDS": "", "CLOSING_CUT": ""}):
        e = ears()
        e.load_greetings = lambda: setattr(e, "greetings", ["ok"])
        e.read_settings()
        assert e.sounds and e.greetings == ["ok"] and e.listen_all and e.followup == 100 and e.closing_gap == 10
    # With sounds off, no chime plays, and a spoken line still does.
    e = listener.Ears.__new__(listener.Ears)
    e.sounds, e.deaf_until = False, 0.0
    with mock.patch("sounddevice.play") as play, mock.patch("sounddevice.wait"):
        assert e.play(*listener.CHIME_UP, tail=1.0)
        assert not play.called and e.deaf_until < time.monotonic() + 0.1
        e.play(np.zeros(100, np.float32), RATE)
        assert play.called


def bank() -> None:
    """Lines rendered ahead play without the voice, with their age, and a reminder follows a greeting only now and then."""
    e = ears()
    line, age = (np.ones(10, np.float32), RATE), (np.ones(5, np.float32) * 2, RATE)
    e.banked = {"Sir, the vlog is rendering.": line, "As of two minutes ago.": age}
    e.tts = mock.Mock()
    with mock.patch.dict(listener.os.environ, {"VOICE_ENGINE": ""}):
        samples, rate, _ = listener.Ears.speech(e, "Sir, the vlog is rendering. As of two minutes ago.")
        assert rate == RATE and len(samples) == 10 + RATE // 8 + 5 and not e.tts.create.called
        assert len(listener.Ears.speech(e, "Sir, the vlog is rendering.")[0]) == 10 and not e.tts.create.called
        # Anything else is said live.
        e.tts.create.return_value = (np.ones(3, np.float32), RATE)
        assert len(listener.Ears.speech(e, "Sir, something else.")[0]) == 3
        assert len(listener.Ears.speech(e, "Sir, the vlog is rendering. As of a year ago.")[0]) == 3

    chunk = np.ones(listener.CHUNK, np.int16)
    hello = ("Yes, sir.", np.ones(RATE // 2, np.float32), RATE)
    review = "Sir, the draft is ready for your review."

    def wake(e, call=False):
        got = []
        e.greetings, e.greetings_at, e.greeted = [hello], {}, time.monotonic()
        with mock.patch.object(listener, "in_call", lambda: call), mock.patch.object(listener, "emit", lambda ev, **d: got.append((ev, d))), \
                mock.patch.object(listener, "pause_media", list):
            e.oww.predict = lambda _: {"jarvis": 0.9}
            e.on_chunk(chunk)
            e.wait_for_wake()
        return [d["text"] for ev, d in got if ev == "reminder"]

    def ready():
        e = ears()
        e.banked, e.waiting, e.reminded = {review: (np.ones(RATE // 2, np.float32), RATE)}, [review], {}
        return e

    e = ready()
    assert wake(e) == [review] and e.said == f"Yes, sir. {review}"  # what the mic hears of it stays out of the request
    assert wake(e) == []  # not again soon
    e.reminded[review] -= listener.REMIND_EVERY + 1
    assert wake(e) == [review]
    # Nothing waiting, not rendered yet, switched off, or in a call: nothing. Two waiting: one per greeting.
    e = ready()
    e.waiting = []
    assert wake(e) == []
    e = ready()
    e.banked = {}
    assert wake(e) == []
    e = ready()
    e.reminders = False
    assert wake(e) == []
    e = ready()
    assert wake(e, call=True) == []
    e = ready()
    other = "Sir, the build needs you."
    e.banked[other] = e.banked[review]
    e.waiting = [review, other]
    assert wake(e) == [review] and wake(e) == [other] and wake(e) == []


def fixes() -> None:
    """Words the user's terms are often heard as get put right, from the list in words.txt and nothing else."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "words.txt"
        path.write_text("# comment, with an example: # also: a, b\nClaude Code  # also: cloud code\nClaude  # also: Clawed, Clawde\nJev\n", encoding="utf-8")
        got = listener.load_fixes(path)
        terms = listener.load_terms(path)
    assert "Claude Code" in terms and "Jev" in terms and not any("also" in t for t in terms), terms
    with mock.patch.object(listener, "FIXES", got):
        assert listener.fix_words("Ask clawed about cloud code using it") == "Ask Claude about Claude Code using it"
        assert listener.fix_words("clawedback") == "clawedback"
        assert listener.fix_words("a b") == "a b"  # the comment's example is no list
        e, events = ears(), []
        with mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "emit", lambda ev, **d: events.append((ev, d))), \
                mock.patch.object(listener, "transcribe", lambda c: "open clawed"):
            e.request_done(np.ones(listener.RATE, np.int16))
        assert ("heard", {"text": "open Claude", "raw": "open clawed"}) in events
    for term in ("grep", "Jev", "Dentaria"):
        assert term in listener.TERMS, term
    # The real file: comments reach neither the prompt nor the words, and a real "echo" stays.
    assert "#" not in listener.VOCAB and not any("#" in right for _, right in listener.FIXES)
    assert listener.fix_words("use a real echo here") == "use a real echo here"
    assert listener.fix_words("do this, echo cpd") == "do this, reco cpd"


def talk_over() -> None:
    """Talking over a reply stops it, and its own echo, a video, a call or a reply that says the name don't."""
    # The decision: speech only counts when clearly louder than the reply is at the mic.
    def fed(chunks, ratio=2.0):
        t = listener.TalkOver(ratio)
        return t, [t.feed(s, l, float(i)) for i, (s, l) in enumerate(chunks)]
    echo = [(False, 300.0)] * 30
    assert not any(fed(echo)[1])
    assert not any(fed(echo + [(True, 320.0)] * 40)[1])  # the echo, called speech
    assert not any(fed(echo + [(True, 2000.0)] * 5)[1])  # a cough
    assert not any(fed([(False, 300.0)] * 5 + [(True, 2000.0)] * 8)[1])  # too soon to know the echo
    t, got = fed(echo + [(True, 2000.0)] * 8)
    assert got.index(30.0) == 35 and t.peak > 2  # fires on the sixth chunk, with when it began
    assert not any(fed(echo + [(True, 2000.0)] * 8, ratio=8)[1])  # the knob

    rms = np.full(listener.CHUNK, 2000, np.int16)
    still = np.full(listener.CHUNK, 300, np.int16)

    def run(script, text="All done here", quiet=False, media=False, score=0.0, setting=True):
        """Plays `script`, chunks of (level, speech), through listen_over; returns the ears, and how many chunks it took."""
        e, n = ears(), {"n": 0}
        e.talk_over, e.strict = setting, 0.7
        flags = iter(script)
        speech = {"on": False}
        e.vad.predict = lambda *a, **k: 1.0 if speech["on"] else 0.0
        e.oww.predict = lambda c: {"w": score if c[0] == 2000 else 0.0}

        def playing():
            if n["n"] >= len(script):
                return False
            if listener.MIC_TAP.empty():
                chunk, speech["on"] = script[n["n"]]
                n["n"] += 1
                listener.MIC_TAP.put((chunk, float(n["n"])))
            return True
        with mock.patch.object(listener, "emit", lambda *a, **k: None), mock.patch.object(listener, "media_playing", lambda: media):
            e.listen_over(text, quiet, playing, lambda: n.setdefault("stopped", True))
        assert listener.MIC_TAP is None
        return e, n
    reply = [(still, False)] * 30 + [(rms, True)] * 10
    e, n = run(reply)
    assert e.barge and n.get("stopped") and n["n"] < len(reply)
    for how in ({"quiet": True}, {"media": True}, {"setting": False}):
        e, n = run(reply, **how)
        assert not e.barge and "stopped" not in n, how
    # The wake word works in a call too, but the reply's own "Jarvis" doesn't count.
    e, n = run(reply, quiet=True, score=0.9)
    assert e.barge and e.sure and e.woke[0] == 0.9
    e, n = run(reply, "Sir, Jarvis is on it", quiet=True, score=0.9)
    assert not e.barge

    events = []
    with mock.patch.object(listener, "emit", lambda ev, **d: events.append((ev, d))), mock.patch.object(listener, "in_call", lambda: False):
        # The whole turn: stops, records from when they began, and what it hears goes on as a request.
        e = ears()
        e.listen_all = True

        def over_it(samples, rate=0, *a, **k):
            if k.get("over"):
                e.play_began, e.barge = time.monotonic() - 1, time.monotonic() - 0.3  # 1 s into its 2 s of words
            return True
        e.play = over_it
        e.speech = lambda text: (np.zeros(RATE * 2, np.float32), RATE, "test")
        e.say("One two three four five six seven eight nine ten.", asked=False)
        assert e.on_chunk == e.record_chunk and e.on_done == e.request_done and e.cap == listener.MAX_CLIP
        assert e.deaf_until < e.barge and e.cut_rest and ("spoken", {"listening": True}) in events
        assert e.said.split()[-1] != "ten." and len(e.said.split()) < 10  # only what it got to
        rest = e.cut_rest[0]
        # Nobody was there: no words back, so the rest of the reply plays.
        played = []
        e.play = lambda samples, *a, **k: played.append(samples) or True
        with mock.patch.object(listener, "transcribe", lambda c: ""):
            e.request_done(np.ones(RATE, np.int16))
        assert any(p is rest for p in played) and e.cut_rest is None
        # Someone was: nothing of the old reply comes back.
        e.cut_rest = (rest, RATE)
        played.clear()
        with mock.patch.object(listener, "transcribe", lambda c: "stop that one"):
            e.request_done(np.ones(RATE, np.int16))
        assert not any(p is rest for p in played) and e.cut_rest is None
        assert ("heard", {"text": "stop that one"}) in events
        # Not stopped: as before.
        e = ears()
        e.say("Nothing to see.", asked=False)
        assert e.on_chunk == e.wake_chunk and not e.barge


def cut_off() -> None:
    """Back from a stop, or a request lost: says so with where it lost the thread, not in a call, and quiet moments only."""
    now = 1_000_000.0
    state = {"at": now - 8, "phase": "idle", "heard": "remove the interview.", "heard_at": now - 60}
    line = listener.cut_off_line
    assert line(state, "a restart", now, "Sir") == ("Sorry sir, I got cut off by a restart. Last I heard: remove the interview.", False)
    assert line({**state, "phase": "window"}, "", now)[1] is True
    said, listen = line({**state, "phase": "talking"}, "", now)
    assert listen and "I lost what you were just saying" in said and said.endswith("Go ahead.")
    assert line({**state, "clean": True}, "", now)[0] == "" and line({}, "", now)[0] == ""
    assert line({**state, "at": now - listener.CUT_RECENT - 1}, "", now)[0] == ""  # a fresh start
    assert "Last I heard" not in line({**state, "heard_at": now - listener.HEARD_RECENT - 1}, "", now)[0]
    long = line({**state, "heard": " ".join(map(str, range(50)))}, "", now)[0]
    assert "Last I heard: 38 39" in long and " 37 " not in long  # the end of it, never a read-out
    # When a restart may happen.
    calm = {"at": now - 2, "phase": "idle", "lines": 0, "last_speech": now - listener.RESTART_QUIET}
    assert listener.quiet_enough(calm, now)
    for busy in ({"last_speech": now - 30}, {"phase": "talking"}, {"phase": "window"}, {"lines": 1}, {"at": now - 60}):
        assert not listener.quiet_enough({**calm, **busy}, now), busy
    assert not listener.quiet_enough({}, now)
    limited = type("E", (Exception,), {"response": type("R", (), {"status_code": 429})})("429 for url")
    assert listener.why_lost(limited) == "speech to text hit its limit" and "url" not in listener.why_lost(ValueError("url"))

    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(listener, "EARS_STATE", Path(tmp) / "ears.json"), \
            mock.patch.object(listener, "EARS_WHY", Path(tmp) / "ears.why"), mock.patch.object(listener, "in_call", lambda: False):
        events = []
        with mock.patch.object(listener, "emit", lambda ev, **d: events.append((ev, d))):
            # What one listener saves, the next one says: the words survive, and a stop mid-request listens again.
            e = ears()
            e.heard_last, e.heard_at = "open the door", time.time()
            e.record(e.request_done)
            e.voiced = listener.MIN_VOICED
            e.save_state()
            assert listener.read_state()["phase"] == "talking" and listener.read_state()["pid"] == os.getpid()
            listener.EARS_WHY.write_text("a crash", encoding="utf-8")
            back = ears()
            back.came_back()
            assert back.heard_last == "open the door" and not listener.EARS_WHY.exists()
            assert back.queue == []  # not before the mic opens
            back.say_cut_off()
            (text, how), = back.queue
            assert "cut off by a crash" in text and "Last I heard: open the door." in text
            assert how == {"asked": True, "hold": True, "window": True, "toast": False}
            assert ("cut_off", {"text": text}) in events and back.user_turn()  # it listens first, in case they're talking
            back.say_cut_off()
            assert len(back.queue) == 1  # once
            # A clean quit: nothing next time. Setting off: nothing at all.
            e.save_state(clean=True)
            quiet = ears()
            quiet.came_back()
            assert quiet.coming_back is None and quiet.heard_last == "open the door"  # but it still knows the words
            e.saved_at = 0.0
            e.save_state()
            off = ears()
            off.cut_off = False
            off.came_back()
            off.say_cut_off()
            assert off.queue == []

            # The restart command: says why, stops only a listener that's alive, and never a stale pid.
            listener.EARS_STATE.write_text(json.dumps({"pid": 99999, "at": time.time(), "phase": "idle", "lines": 0,
                                                       "last_speech": time.time() - listener.RESTART_QUIET}), encoding="utf-8")
            with mock.patch.object(listener.os, "kill") as kill, mock.patch("builtins.print"):
                assert listener.restart(["my", "update"]) == 0
                kill.assert_called_once_with(99999, 15)
                assert listener.EARS_WHY.read_text(encoding="utf-8") == "my update"
                listener.EARS_WHY.unlink()
                listener.EARS_STATE.write_text(json.dumps({"pid": 99999, "at": time.time() - 60}), encoding="utf-8")
                assert listener.restart(["--now"]) == 1 and kill.call_count == 1 and not listener.EARS_WHY.exists()

            # A lost request: said once, listens again, and off means off.
            events.clear()
            e = ears()
            e.heard_last, e.heard_at = "open the door", time.time()
            with mock.patch.object(listener, "transcribe", mock.Mock(side_effect=limited)):
                e.request_done(np.ones(listener.RATE, np.int16))
                (text, how), = e.queue
                assert "I lost that: speech to text hit its limit. Last I heard: open the door. Say it again." in text
                assert how == {"hold": True, "toast": False} and ("lost", {"text": text}) in events and e.on_chunk == e.wake_chunk
                e.request_done(np.ones(listener.RATE, np.int16))  # again at once: no loop
                assert len(e.queue) == 1
                off = ears()
                off.cut_off = False
                off.request_done(np.ones(listener.RATE, np.int16))
                assert off.queue == []
            # In a call it's held, not said.
            e.queue, e.spoken = [], []
            with mock.patch.object(listener, "in_call", lambda: True):
                e.say(text, hold=True, toast=False)
            assert ("held", {"text": text}) in events and e.spoken == []


def greeting() -> None:
    """Waking says a few words, not the same ones twice running, and never in a call or over the request."""
    chunk = np.ones(listener.CHUNK, np.int16)
    sound = lambda: np.ones(RATE // 2, np.float32)
    lines = [(f"Line {i}, sir.", sound(), RATE) for i in range(3)]
    morning = ("Morning, sir.", sound(), RATE)

    def wake(e, call=False):
        events = []
        with mock.patch.object(listener, "in_call", lambda: call), mock.patch.object(listener, "emit", lambda ev, **d: events.append((ev, d))), \
                mock.patch.object(listener, "pause_media", list):
            e.oww.predict = lambda _: {"jarvis": 0.9}
            e.on_chunk(chunk)
        return [d["text"] for ev, d in events if ev == "greeting"]

    def ready():
        e = ears()
        e.greetings, e.greetings_at = lines, {"Morning": morning, "Good day": morning, "Evening": morning}
        e.greeted = time.monotonic()
        return e

    e = ready()
    said = [wake(e)[0] for _ in range(1)]
    for _ in range(30):
        e.wait_for_wake()
        said += wake(e)
    assert all(a != b for a, b in zip(said, said[1:])) and set(said) == {g[0] for g in lines}, said
    assert e.played[-1] is next(g[1] for g in lines if g[0] == said[-1])
    assert e.on_chunk == e.after_wake and e.said == said[-1]
    # The mic keeps counting from the moment it woke, and hears no more than the words.
    assert e.deaf_until <= time.monotonic() and e.deaf_until == e.greeted
    # Away a while, or just started: the time of day.
    e = ready()
    e.greeted = time.monotonic() - listener.GREETING_AWAY - 1
    assert wake(e) == ["Morning, sir."]
    e = ready()
    e.greeted = 0.0
    assert wake(e) == ["Morning, sir."]
    # In a call: no words, as ever only the chime. Off, or not rendered: the chime.
    e = ready()
    assert wake(e, call=True) == [] and is_sound(e.played, listener.CHIME_UP)
    e = ears()
    assert wake(e) == [] and is_sound(e.played, listener.CHIME_UP)
    # What the mic hears of it stays out of the request.
    assert listener.strip_echo("Yes, sir. Status.", "Yes, sir.", late=True) == "Status."
    assert listener.strip_echo("I'm here, sir.", "I'm here, sir.", late=True) == ""
    # Each pool entry fits the phrase rules: no closing phrase and no wake word to trip on.
    for word in listener.GREETINGS + list(listener.GREETINGS_AT):
        for title in ("Sir", ""):
            text = listener.greeting_text(word, title)
            assert not listener.closes(text) and not listener.re.search(listener.NAMES, text, listener.re.I), text
    # Too long, or silent: left out. A voice that fails: the chime, not a dead wake.
    e = ears()
    long, ok = np.ones(RATE * 2, np.float32), np.ones(RATE // 2, np.float32)
    e.load_ack = lambda text, speed=1: (long if text.startswith("Yes") else ok, RATE)
    with mock.patch.dict(listener.os.environ, {"VOICE_TITLE": "Sir"}), mock.patch.object(listener, "emit"):
        e.load_greetings()
    assert e.greetings and not any(g[0].startswith("Yes") for g in e.greetings) and "Morning" in e.greetings_at
    e.load_ack = lambda text, speed=1: (_ for _ in ()).throw(RuntimeError("no voice"))
    with mock.patch.object(listener, "emit"):
        e.load_greetings()
    assert not e.greetings


def closing_cut() -> None:
    """A request that ends with a closing phrase goes at once. Mid-sentence, or with a failure, silence decides as before."""
    for said in ("Do it.", "Yeah, do it.", "yeah do it", "Fix the navbar. Go ahead.", "Okay, thank you.", "Send it.", "Status. Go.",
                 "Hey Jarvis, do it.", "Fine, thanks", "That's it.", "Fix that, then do it.", "Please send it.", "It works. Let's go.", "Yeah, let's do it."):
        assert listener.closes(said), said
    for said in ("How do I do it", "Can you do it", "Where did it go?", "I want to go", "I'll send it", "do it again", "Go to the page",
                 "thank you for that", "tell them thank you", "", "Going", "Thank you."):
        assert not listener.closes(said), said

    chunk = np.ones(listener.CHUNK, np.int16)

    def talk(saying, fail=False):
        """Four chunks of speech, then quiet: how many chunks of quiet until it ended, and what it asked."""
        e, sent, asked = ears(), [], []
        e.closing_gap, e.next_closing = 10, 0.0

        def stt(clip, timeout=600):
            asked.append(len(clip))
            assert timeout == listener.CLOSING_TIMEOUT
            if fail:
                raise RuntimeError("offline")
            return saying

        with mock.patch.object(listener, "transcribe", stt), mock.patch.object(listener, "emit", lambda *a, **k: None):
            e.record(sent.append)
            e.vad.predict = lambda *a, **k: 0.9
            for _ in range(4):
                e.on_chunk(chunk)
            e.vad.predict = lambda *a, **k: 0.0
            n = 0
            while not sent and n < 200:
                e.on_chunk(chunk)
                n += 1
        return n, sent, asked

    n, sent, asked = talk("Fix it. Do it.")
    assert n == 10 and len(sent) == 1 and asked == [(4 + 2) * listener.CHUNK], (n, asked)  # the words, not the quiet
    # Not a closing, or speech to text down: only silence ends it, after one check.
    for kw in ({"saying": "Fix the navbar"}, {"saying": "Do it.", "fail": True}):
        n, sent, asked = talk(**kw)
        assert n == listener.END_QUIET and len(sent) == 1 and len(asked) == 1, (kw, n)
    # Going on after the pause: another pause checks again, but not within CLOSING_EVERY, for Groq's limit.
    e, sent, asked = ears(), [], []
    e.closing_gap = 2
    with mock.patch.object(listener, "transcribe", lambda clip, timeout=600: asked.append(1) or "go on"), mock.patch.object(listener, "emit", lambda *a, **k: None):
        e.record(sent.append)
        for _ in range(3):
            e.vad.predict = lambda *a, **k: 0.9
            for _ in range(4):
                e.on_chunk(chunk)
            e.vad.predict = lambda *a, **k: 0.0
            for _ in range(3):
                e.on_chunk(chunk)
    assert len(asked) == 1 and not sent, asked
    # Near Groq's limit the nice-to-haves step aside, the closing check before what the user said.
    with mock.patch.object(listener, "groq_calls", listener.deque([time.monotonic()] * 12, maxlen=20)):
        assert not listener.groq_room(listener.LIVE_SPARE) and listener.groq_room(listener.CLOSING_SPARE)
        live = listener.GroqLive()
        live.waiting = listener.LIVE_EVERY
        live.feed(chunk)
        assert not live.busy
    with mock.patch.object(listener, "groq_calls", listener.deque([time.monotonic()] * 16, maxlen=20)):
        e = ears()
        e.closing_gap = 5
        e.record(sent.append)
        assert not listener.groq_room(listener.CLOSING_SPARE) and not e.said_closing()
    # Off, and voice training never checks.
    e = ears()
    assert e.closing_gap == 0
    e.record(sent.append)
    assert not e.said_closing()
    e = ears()
    e.closing_gap, e.on_done = 5, e.take_done
    assert not e.said_closing()


def echo() -> None:
    """The mic opens before a reply ends, by when the words reached the mic. Its echo never reaches the boss."""
    said = "Sir, the vlog is ready, so tell me when to post it. Is that okay?"
    strip = listener.strip_echo
    assert strip("Is that okay?", said, late=False) == ""  # all echo
    assert strip("Post it. Is that okay?", said, late=True) == ""
    assert strip("Is that okay? Yes, post it now.", said, late=True) == "Yes, post it now."  # talking over the end
    assert strip("Uh, that okay? Yes.", said, late=True) == "Yes."  # one garbled word first
    assert strip("Okay", said, late=False) == ""  # the last word and no speech past it
    assert strip("Okay", said, late=True) == "Okay"  # the user's answer
    assert strip("Yes, please post it to the first page.", said, late=True) == "Yes, please post it to the first page."
    assert strip("Tell me a joke", said, late=True) == "Tell me a joke"
    assert strip("anything", "", late=False) == "anything"
    # As Whisper did with a reply mixed in at 130 to 2000 RMS before a real request (nothing played).
    long = "Sir, the vlog is ready, so tell me when you want it posted to the first page on the list."
    assert strip("When you want it posted to the first page on the list. So, there should be a", long, late=True) == "So, there should be a"

    def say(e, text):
        with mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "emit"), mock.patch("soundfile.write"), \
                mock.patch.object(listener.os, "replace"), mock.patch.object(listener, "output_problem", lambda: ""), \
                mock.patch.object(listener, "pause_media", list), mock.patch.object(listener, "resume_media"), mock.patch.object(listener.time, "monotonic", lambda: 1000.0):
            e.say(text)

    # The timing: a chunk from a second before the last word counts, and one before that doesn't.
    e = ears()
    e.lead, e.followup = 1.0, 0
    say(e, "Hello there.")
    assert e.said == "Hello there." and abs(e.words_end - 999.93) < 1e-6 and abs(e.deaf_until - 998.93) < 1e-6
    # With a window, the pad and chime after the words don't count.
    e = ears()
    e.lead = 0.5
    e.speech = lambda text: (np.zeros(RATE, np.float32), RATE, "test")
    say(e, "Do you want it?")
    pad = (RATE * 6 // 10 + len(listener.CHIME_UP[0])) / RATE
    assert abs(e.words_end - (1000 - pad - 0.07)) < 1e-6 and abs(e.deaf_until - (e.words_end - 0.5)) < 1e-6
    assert e.on_chunk == e.record_chunk

    clip = np.ones(listener.RATE, np.int16)

    def heard(words_end):
        e, events = ears(), []
        e.said, e.words_end = "Do you want it?", words_end
        with mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "emit", lambda ev, **d: events.append((ev, d))), \
                mock.patch.object(listener, "transcribe", lambda c: "you want it"):
            e.request_done(clip)
        return [d["text"] for ev, d in events if ev == "heard"]

    assert heard(time.monotonic()) == []  # the clip reaching the boss loses the echo
    assert heard(time.monotonic() - 60) == ["you want it"]  # long after the reply, it isn't compared at all


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
    cut_off()
    talk_over()

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
    # Silent files in sounds/local, the user's choice, have no pitch to compare.
    assert not max(known) or pitch(listener.CHIME_NEAR) > 1.5 * max(known), known

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
    listen_after()
    settings()
    bank()
    fixes()
    greeting()
    closing_cut()
    echo()
    mic_names()
    staying_quiet()
    print("ok")


if __name__ == "__main__":
    sys.exit(main())
