"""Speech fallback chain: speak (Sonic) -> speak_text; static phrases -> speak_cached; no Mac app -> say."""
import base64
from urllib.parse import parse_qs, urlparse

import pytest

from conftest import Harness, make_settings, snapshot
from fakes import FakeSonic

TEXT = "The sugar is at your one o'clock, about an arm's length away."


def tts_settings(tmp_path, url, **kw):
    base = dict(cartesia_api_key="sk_car_test", voice_id="voice-123", tts_url=url + "/tts/websocket",
                tts_first_chunk_timeout_s=0.3)
    base.update(kw)
    return make_settings(tmp_path, **base)


@pytest.fixture
async def sonic():
    srv = await FakeSonic().start()
    yield srv
    await srv.stop()


async def ready(settings, mac_app=True):
    h = Harness(settings, mac_app=mac_app)
    await h.feed(snapshot())
    h.clear()
    return h


async def test_streams_speak_chunks(tmp_path, sonic):
    h = await ready(tts_settings(tmp_path, sonic.url))
    out = await h.say("Where's the sugar?")
    chunks = h.of("speak", out)
    assert [c["seq"] for c in chunks] == [0, 1, 2, 3]
    assert chunks[0]["text"] == TEXT and all("text" not in c for c in chunks[1:])
    assert [c["final"] for c in chunks] == [False, False, False, True] and chunks[-1]["chunk_b64"] == ""
    assert base64.b64decode(chunks[1]["chunk_b64"]) == bytes([1]) * 8
    assert {c["format"] for c in chunks} == {"pcm_f32le"} and {c["sample_rate"] for c in chunks} == {48000}
    assert chunks[0]["utterance_id"] == h.of("guide_start", out)[0]["utterance_id"]
    [req] = sonic.requests
    assert req["model_id"] == "sonic-3.6-2026-08-27" and req["voice"] == "voice-123"
    assert req["output_format"] == {"container": "raw", "encoding": "pcm_f32le", "sample_rate": 48000}
    assert req["continue"] is False and req["max_buffer_delay_ms"] == 0 and req["transcript"] == TEXT
    assert sonic.auth[0] == "Bearer sk_car_test"
    # the socket is reused for the next utterance
    await h.say("Where's the salt?")
    assert len(sonic.auth) == 1 and len(sonic.requests) == 2


@pytest.mark.parametrize("mode", ["error", "slow", "drop"])
async def test_tts_failure_falls_back_to_speak_text(tmp_path, sonic, mode):
    sonic.mode = mode
    h = await ready(tts_settings(tmp_path, sonic.url))
    out = await h.say("Where's the sugar?")
    assert not h.of("speak", out)
    assert [m["text"] for m in h.of("speak_text", out)] == [TEXT]
    assert h.core.speaker.mode == "system"


async def test_unreachable_tts_falls_back(tmp_path):
    h = await ready(tts_settings(tmp_path, "ws://127.0.0.1:9"))
    out = await h.say("Where's the sugar?")
    assert [m["text"] for m in h.of("speak_text", out)] == [TEXT]


async def test_static_phrase_uses_speak_cached_even_with_tts(tmp_path, sonic):
    h = await ready(tts_settings(tmp_path, sonic.url))
    out = await h.say("stop")
    [c] = h.of("speak_cached", out)
    assert c["phrase_id"] == "stopping" and c["text"] == "Okay, stopping."
    assert not sonic.requests


async def test_text_equal_to_a_phrase_is_cached(settings):
    h = await ready(settings)
    await h.core.speaker.say("u-1", "Sorry, I didn't catch that.")
    assert h.of("speak_cached")[0]["phrase_id"] == "not_understood"


async def test_no_tts_key_sends_speak_text(settings):
    h = await ready(settings)
    out = await h.say("Where's the sugar?")
    assert [m["text"] for m in h.of("speak_text", out)] == [TEXT]


async def test_no_mac_app_uses_local_say(tmp_path):
    marker = tmp_path / "said.txt"
    script = tmp_path / "fake_say"
    script.write_text(f'#!/bin/sh\necho "$@" >> {marker}\n')
    script.chmod(0o755)
    h = await ready(make_settings(tmp_path, say_cmd=str(script)), mac_app=False)
    out = await h.say("Where's the sugar?")
    assert not h.of("speak_text", out) and not h.of("speak_cached", out)
    assert h.of("guide_start", out)
    assert marker.read_text().strip() == TEXT
