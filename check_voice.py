"""Checks the interruption rules without a mic or a speaker. Run: .venv\\Scripts\\python check_voice.py

  say    a reply to a request opens the follow-up window, a line nobody asked for does not
  call   in a call: a heads-up at most every HEADS_UP_GAP seconds, the line held; never a window
  media  what was playing resumes after the line, or after the window when one opens
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
    e.on_chunk = e.wake_chunk
    e.spoken = []
    e.speech = lambda text: (e.spoken.append(text), np.zeros(10, np.float32), RATE, "test")[1:]
    e.play = lambda *a, **k: None
    return e


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

    # A line nobody asked for leaves a request being recorded alone.
    with mock.patch.object(listener, "in_call", lambda: False), mock.patch.object(listener, "emit"), \
            mock.patch.object(listener, "pause_media", lambda: []), \
            mock.patch.object(listener, "REPLY_WAV", HERE / "tmp" / "check_voice.wav"):
        e = ears()
        e.on_chunk = e.record_chunk
        e.say("The news.", asked=False, hold=True)
    assert e.on_chunk == e.record_chunk

    subprocess.run(["node", "--input-type=module", "-e", """
        import assert from 'node:assert'
        import { asksForHeld as a, verbFor as v } from './rules.mjs'
        assert.equal(v(0, 1e9), 'tell')
        assert.equal(v(1e9 - 10_000, 1e9), 'say')
        assert.equal(v(1e9 - 300_000, 1e9), 'late')
        assert.equal(v(1e9 - 3_600_000, 1e9), 'tell')
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
