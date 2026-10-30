"""Checks the interruption rules without a mic or a speaker. Run: .venv\\Scripts\\python check_voice.py

  queue  while the user has the floor every line waits, and goes out oldest first once they are done
  play   each sound gets the silence that lets it play to its end
  say    a line that wants an answer opens the follow-up window, prompted or not; an acknowledgment or plain news does not
  call   in a call: a heads-up at most every HEADS_UP_GAP seconds, the line held; never a window
  media  what was playing resumes after the line, or after the window when one opens
  tries  wake word peaks are logged; a near miss ticks, a wake while busy gets the still-working sound, neither in a call
  rules  rules.mjs picks say, late or tell, and knows what asks for a held line
  scan   the real WASAPI and media session calls run on this machine (nothing is paused)
"""
import subprocess
import sys
from pathlib import Path
from unittest import mock

import numpy as np

import listener

HERE = Path(__file__).resolve().parent
RATE = listener.CHIME_UP[1]


def ears() -> listener.Ears:
    """Ears without its models, with a silent speaker that records what it was told to play."""
    e = listener.Ears.__new__(listener.Ears)
    e.followup, e.busy_until, e.deaf_until, e.next_heads_up, e.paused = 100, 50.0**9, 0.0, 0.0, []
    e.oww, e.vad, e.recent = mock.Mock(), mock.Mock(), []
    e.on_chunk, e.voiced = e.wake_chunk, 0
    e.threshold, e.peak, e.peak_word, e.next_cue, e.acks, e.words = 0.4, 0.0, "", 0.0, {"jarvis": "ack"}, ["jarvis"]
    e.spoken, e.played, e.queue, e.queue_since, e.last_speech = [], [], [], 0.0, 0.0
    e.vad.predict = lambda *a, **k: 0.0
    e.speech = lambda text: (e.spoken.append(text), np.zeros(10, np.float32), RATE, "test")[1:]
    e.play = lambda samples, *a, **k: e.played.append(samples)
    return e


def tries(scores: list[float], busy: bool = False, call: bool = False) -> tuple[listener.Ears, list, list]:
    """Feeds these wake word scores in, one per chunk; returns the ears, the events, and the sounds played."""
    events = []
    with mock.patch.object(listener, "in_call", lambda: call), \
            mock.patch.object(listener, "emit", lambda event, **d: events.append((event, d))):
        e = ears()
        e.busy_until = 1e12 if busy else 0.0
        for score in scores:
            e.oww.predict = lambda _, s=score: {"jarvis": s}
            e.on_chunk(np.zeros(1280, np.int16))
    return e, events, e.played


def is_sound(played: list, *sounds: tuple) -> bool:
    return len(played) == len(sounds) and all(p is s[0] for p, s in zip(played, sounds))


def pitch(sound: tuple[np.ndarray, int]) -> float:
    spectrum = np.abs(np.fft.rfft(sound[0]))
    return float(np.fft.rfftfreq(len(sound[0]), 1 / sound[1])[spectrum.argmax()])


def pulses(sound: tuple[np.ndarray, int]) -> int:
    loud = np.abs(sound[0]) > 0.5 * np.abs(sound[0]).max()
    hops = max(1, sound[1] // 200)  # 5 ms: one cycle of a low note never counts as a gap
    frames = [loud[i:i + hops].any() for i in range(0, len(loud), hops)]
    return sum(1 for a, b in zip([False] + frames, frames) if b and not a)


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


def main() -> None:
    video = object()

    # A reply: in full, then the window, with the video still paused until the window ends.
    e, events, resumed = run(False, [video])
    assert e.on_chunk == e.record_chunk and e.spoken == ["The news."] and e.busy_until == 0
    assert not resumed and e.paused == [video]
    # Nobody asked: in full, no window, the video back at once, and a pending request still counts as pending.
    e, events, resumed = run(False, [video], asked=False, hold=True)
    assert e.on_chunk == e.wake_chunk and e.spoken == ["The news."] and resumed == [video] and e.busy_until > 0
    # A reply that ends the exchange: in full, no window, the video back at once, the wake word free again.
    e, events, resumed = run(False, [video], window=False)
    assert e.on_chunk == e.wake_chunk and e.spoken == ["The news."] and resumed == [video] and e.busy_until == 0
    # Nothing was playing: nothing resumes.
    assert run(False, [], asked=False)[2] == []

    # A call: a heads-up, the line held, no window.
    with mock.patch.dict(listener.os.environ, {"VOICE_TITLE": "Sir"}):
        e, events, resumed = run(True, [video], asked=False, hold=True)
    assert e.spoken == ["Sir, I have an update."] and ("held", {"text": "The news."}) in events
    assert e.on_chunk == e.wake_chunk and resumed == [video]
    # The second line in that call is only held.
    with mock.patch.object(listener, "in_call", lambda: True), mock.patch.object(listener, "emit"):
        e.spoken.clear()
        e.say("More news.", asked=False, hold=True)
    assert e.spoken == []
    # In a call the user asked: in full, but still no window.
    e, _, _ = run(True, [], asked=True)
    assert e.spoken == ["The news."] and e.on_chunk == e.wake_chunk
    # An older request in a call waits like any other line.
    e, events, _ = run(True, [], asked=True, hold=True)
    assert e.spoken[0].endswith("I have an update.") and events[0][0] == "held"

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

    # A question with nobody talking and no call: in full, with the window. In a call: the heads-up, no window.
    e, _, _ = run(False, [], hold=True)
    assert e.spoken == ["The news."] and e.on_chunk == e.record_chunk
    e, events, _ = run(True, [], hold=True)
    assert e.spoken[0].endswith("I have an update.") and e.on_chunk == e.wake_chunk and events[0][0] == "held"

    # A near miss: its peak is logged and it ticks once the try is over, not while the score still climbs.
    e, events, played = tries([0.05, 0.3, 0.35])
    assert played == [] and not [ev for ev in events if ev[0] == "peak"]
    e, events, played = tries([0.05, 0.3, 0.35, 0.05])
    assert ("peak", {"word": "jarvis", "score": 0.35, "busy": False}) in events and is_sound(played, listener.CHIME_NEAR)
    # Too low for a tick, but in the log. Noise stays out of it.
    e, events, played = tries([0.2, 0.05])
    assert events == [("peak", {"word": "jarvis", "score": 0.2, "busy": False})] and played == []
    assert tries([0.05, 0.09, 0.0])[1] == []
    # Two near misses in a row: one tick.
    assert is_sound(tries([0.3, 0.05, 0.3, 0.05])[2], listener.CHIME_NEAR)
    # The wake word: the pop and recording, as before, with its score in the log.
    e, events, played = tries([0.5])
    assert [ev[0] for ev in events] == ["peak", "wake"] and is_sound(played, listener.CHIME_UP)
    assert e.on_chunk == e.after_wake
    # While a request waits for its reply: the still-working sound, no wake, and no tick for a near miss.
    e, events, played = tries([0.5], busy=True)
    assert is_sound(played, listener.CHIME_BUSY) and e.on_chunk == e.wake_chunk and "wake" not in [ev[0] for ev in events]
    assert events[0] == ("peak", {"word": "jarvis", "score": 0.5, "busy": True})
    assert tries([0.3, 0.05], busy=True)[2] == []
    # In a call both stay silent, and the score still reaches the log.
    assert tries([0.3, 0.05], call=True)[2] == [] and tries([0.5], busy=True, call=True)[2] == []
    assert tries([0.3, 0.05], call=True)[1][0][0] == "peak"

    # The two new sounds against the three the user knows: pitch for the tick and for the pulses, then the pulse count.
    known = [pitch(s) for s in (listener.CHIME_UP, listener.CHIME_DOWN, listener.CHIME_CLOSE)]
    assert pitch(listener.CHIME_NEAR) > 1.5 * max(known), known
    assert pitch(listener.CHIME_BUSY) < 0.9 * min(known), known
    assert pulses(listener.CHIME_BUSY) == 3 and pulses(listener.CHIME_NEAR) == 1

    subprocess.run(["node", "--input-type=module", "-e", """
        import assert from 'node:assert'
        import { asksForHeld as a, asksSomething as q, isAnswer as n, isLong as l, verbFor as v } from './rules.mjs'
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
    print("ok")


if __name__ == "__main__":
    sys.exit(main())
