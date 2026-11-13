"""Checks for gemini.py without a network: a stand-in Live session. A hand-over goes on as any request (to Groq and the
router); its own answer plays and ends the turn; a failure, or no answer, leaves the listener's own path running; and
the request ending locally drops Gemini."""
from unittest import mock

import numpy as np

import check_voice  # its stand-ins, and no early text in checks
import gemini
import listener

CHUNK = np.ones(listener.CHUNK, np.int16)


class FakeLive:
    def __init__(self, key):
        self.events, self.fed, self.closed, self.heard, self.said = gemini.queue.Queue(), [], False, "hello there", "Hello, sir."

    def feed(self, chunk):
        self.fed.append(chunk)

    def close(self):
        self.closed = True


def ears():
    e = check_voice.ears()
    e.__class__ = gemini.GeminiEars
    e.gemini = None
    return e


def main() -> None:
    with mock.patch.object(gemini, "Live", FakeLive), mock.patch.dict(gemini.os.environ, {"GEMINI_API_KEY": "k"}), \
            mock.patch.object(listener, "emit"):
        # Handed over: on_done gets the clip at once, and Gemini is closed.
        e, sent = ears(), []
        e.record(sent.append, [CHUNK])
        g = e.gemini
        assert not g.fed, "the wake word itself isn't sent"
        e.vad.predict = lambda *a, **k: 0.9
        for _ in range(5):
            e.on_chunk(CHUNK)
        g.events.put(("call", None))
        e.on_chunk(CHUNK)
        assert len(sent) == 1 and g.closed and e.gemini is None and len(g.fed) == 6
        # Handed over while Smart Turn hears it unfinished: ignored, Gemini stays open; finished: handed over.
        e, sent = ears(), []
        e.turn = mock.Mock(run=lambda *a: [np.array([0.1])])
        e.record(sent.append)
        g = e.gemini
        e.vad.predict = lambda *a, **k: 0.9
        e.on_chunk(CHUNK)
        g.events.put(("call", None))
        e.on_chunk(CHUNK)
        assert not sent and e.gemini is g and not g.closed
        e.turn = mock.Mock(run=lambda *a: [np.array([0.5])])
        g.events.put(("call", None))
        e.on_chunk(CHUNK)
        assert len(sent) == 1 and g.closed
        # Its own answer: played, said, and back to the wake word; the listener's path never ends the request.
        e, sent, played = ears(), [], []
        e.record(sent.append)
        g = e.gemini
        g.events.put(("audio", b"\0\0" * 10))
        g.events.put(("audio", b"\0\0" * 10))
        g.events.put(("done", None))

        class Out:
            def __init__(self, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def write(self, b): played.append(len(b))
        with mock.patch("sounddevice.RawOutputStream", Out), mock.patch.object(listener.Ears, "hush", lambda self: None):
            e.on_chunk(CHUNK)
        assert not sent and played[:2] == [20, 20] and g.closed and e.on_chunk == e.wake_chunk and e.said == "Hello, sir."
        # A failure: the listener goes on, and ends the request itself.
        e, sent = ears(), []
        e.record(sent.append)
        e.gemini.events.put(("failed", "no key"))
        e.vad.predict = lambda *a, **k: 0.9
        for _ in range(listener.MIN_VOICED + 1):
            e.on_chunk(CHUNK)
        assert e.gemini is None
        e.vad.predict = lambda *a, **k: 0.0
        for _ in range(e.end_quiet):
            e.on_chunk(CHUNK)
        assert len(sent) == 1
        # The request ended locally first: Gemini is closed, and a late answer is never played.
        e = ears()
        e.record(lambda clip: e.wait_for_wake())
        g = e.gemini
        e.vad.predict = lambda *a, **k: 0.9
        for _ in range(listener.MIN_VOICED + 1):
            e.on_chunk(CHUNK)
        e.vad.predict = lambda *a, **k: 0.0
        for _ in range(e.end_quiet):
            e.on_chunk(CHUNK)
        assert g.closed and e.gemini is None
        # Voice training never goes to Gemini.
        e = ears()
        e.record(e.take_done)
        assert e.gemini is None
    print("ok")


if __name__ == "__main__":
    main()
