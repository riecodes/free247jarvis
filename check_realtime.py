"""Checks realtime.py against a local stand-in for OpenAI's Realtime API: no key, no cost, no mic, no sound.
Run: .venv\\Scripts\\python check_realtime.py
"""
import base64
import json
import threading
import time
from unittest import mock

import numpy as np
from websockets.sync.server import serve

import check_voice
import listener
import realtime

CHUNK = np.ones(listener.CHUNK, np.int16)
got = []  # what the stand-in received
scripts = {"response.create": [], "input_audio_buffer.append": []}  # what it answers each with, once


def handler(ws) -> None:
    for message in ws:
        event = json.loads(message)
        got.append(event)
        for reply in scripts.get(event["type"], [])[:]:
            scripts[event["type"]].remove(reply)
            ws.send(json.dumps(reply))


def wait(test, what: str) -> None:
    for _ in range(300):
        if test():
            return
        time.sleep(0.01)
    raise AssertionError(what)


def ears() -> realtime.RealtimeEars:
    e = check_voice.ears()
    e.__class__ = realtime.RealtimeEars
    e.session = realtime.Session("test")
    return e


def main() -> None:
    events, played = [], []

    class Out:
        def __init__(self, **how):
            assert how["samplerate"] == realtime.RATE

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def write(self, sound):
            played.append(sound)

    server = serve(handler, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"ws://127.0.0.1:{server.socket.getsockname()[1]}/?model={{model}}"
    words = lambda text: {"type": "conversation.item.input_audio_transcription.completed", "transcript": text}
    audio = lambda data: {"type": "response.output_audio.delta", "delta": base64.b64encode(data).decode()}

    with mock.patch.object(realtime, "URL", url), mock.patch.object(listener, "emit", lambda ev, **d: events.append((ev, d))), \
            mock.patch.object(listener, "transcribe", realtime.transcribe), mock.patch.object(listener, "in_call", lambda: False), \
            mock.patch.object(listener, "output_problem", lambda: ""), mock.patch("sounddevice.RawOutputStream", Out), \
            mock.patch.object(realtime, "plain_transcribe", lambda clip: "from the listener"), mock.patch.object(listener, "pause_media", list):
        # Connecting: only the end of a turn comes back, the router decides the reply, and the mic goes up at 24 kHz.
        e = ears()
        e.record(e.request_done, [CHUNK])
        wait(lambda: len(got) >= 3, "no session, clear and pre-roll")
        session = got[0]["session"]["audio"]
        assert got[0]["type"] == "session.update" and session["input"]["turn_detection"]["create_response"] is False
        assert session["input"]["transcription"]["prompt"] == listener.VOCAB
        assert got[2]["type"] == "input_audio_buffer.append" and len(base64.b64decode(got[2]["audio"])) == listener.CHUNK * 3

        # "Hey Jarvis" alone keeps the recording going; the request's words end it at once, with no 5 s of quiet and no
        # chime in the way, and go through the listener's own filters.
        scripts["input_audio_buffer.append"].append(words("Hey Jarvis."))
        e.record_chunk(CHUNK)
        wait(lambda: e.session.text is not None, "no words")
        e.record_chunk(CHUNK)
        assert e.on_chunk == e.record_chunk and e.streaming and not [x for x in events if x[0] == "heard"]
        scripts["input_audio_buffer.append"].append(words("Hey Jarvis, open notepad"))
        e.record_chunk(CHUNK)
        wait(lambda: e.session.text is not None, "no words")
        e.play = lambda samples, *a, **k: played.append(samples) or True
        e.record_chunk(CHUNK)
        assert ("heard", {"text": "open notepad"}) in events and e.on_chunk == e.wake_chunk and not e.streaming
        assert realtime.told is None and listener.heard_how == {"engine": "openai"}

        # The "heard you" sound is skipped only with the session's words in hand.
        with mock.patch.object(realtime, "told", "words"), mock.patch.object(listener.Ears, "play", side_effect=AssertionError):
            assert realtime.RealtimeEars.play(e, *listener.CHIME_DOWN)

        # A reply plays as it arrives, leaves the conversation out, and a line that asks opens the follow-up window.
        events.clear(), played.clear()
        scripts["response.create"] += [audio(b"ab"), audio(b"cd"), {"type": "response.done"}]
        e.say("Which one?")
        sent = [x for x in got if x["type"] == "response.create"][-1]["response"]
        assert sent["conversation"] == "none" and sent["input"][0]["content"][0]["text"] == "Which one?"
        assert played[:2] == [b"ab", b"cd"] and ("said", {"text": "Which one?"}) in events and ("spoken", {"listening": True}) in events
        assert e.streaming and e.on_chunk == e.record_chunk

        # What goes wrong before the first sound is said by the listener's own voice.
        e = ears()
        e.session.open()
        e.play = lambda samples, *a, **k: played.append(samples) or True
        played.clear()
        scripts["response.create"] += [{"type": "error", "error": {"message": "over quota"}}]
        with mock.patch("soundfile.write"), mock.patch.object(listener.os, "replace"):
            e.say("Done.", asked=False)
        assert e.spoken == ["Done."] and played, "the fallback voice did not speak"

        # In a call, a line nobody asked for waits unsaid and costs nothing, and no audio goes up for a voice training take.
        e.spoken.clear(), events.clear()
        requests = len([x for x in got if x["type"] == "response.create"])
        with mock.patch.object(listener, "in_call", lambda: True):
            e.say("News.", asked=False, hold=True)
        assert e.spoken == [] and ("held", {"text": "News."}) in events
        assert len([x for x in got if x["type"] == "response.create"]) == requests
        e.record(e.take_done)
        assert not e.streaming

        # No connection: the listener's end of speech and speech to text do it all.
        e = ears()
        with mock.patch.object(realtime, "URL", "ws://127.0.0.1:9/?model={model}"):
            e.record(e.request_done, [CHUNK])
        assert not e.streaming and e.live is None
        e.play = lambda samples, *a, **k: True
        e.vad.predict = lambda *a, **k: 0.9
        for _ in range(listener.MIN_VOICED):
            e.record_chunk(CHUNK)
        e.vad.predict = lambda *a, **k: 0.0
        events.clear()
        for _ in range(listener.END_QUIET):
            e.record_chunk(CHUNK)
        assert ("heard", {"text": "from the listener"}) in events, events
    server.shutdown()
    print("ok")


if __name__ == "__main__":
    main()
