"""Cartesia Ink STT against fake servers: transcripts, lazy open/close, fallback, recovery."""
import asyncio
import base64
import struct
from urllib.parse import parse_qs, urlparse

import pytest

from conftest import Harness, make_settings, snapshot
from earmark_contracts import MicAudio
from fakes import FakeInk, wait_until

CHUNK = base64.b64encode(bytes(3200)).decode()  # 100 ms of 16 kHz s16le, silence
LOUD = base64.b64encode(struct.pack("<h", 8000) * 1600).decode()  # 100 ms of 16 kHz s16le, loud


def stt_settings(tmp_path, url, **kw):
    base = dict(cartesia_api_key="sk_car_test", stt_url=url + "/stt/turns/websocket",
                stt_connect_timeout_s=0.3, stt_first_event_timeout_s=0.5, stt_idle_close_s=0.4,
                stt_probe_interval_s=0.2)
    base.update(kw)
    return make_settings(tmp_path, **base)


async def stream(h, n=10, seq0=0, dt=0.02, chunk=CHUNK):
    for i in range(n):
        await h.core.handle(MicAudio(seq=seq0 + i, sample_rate=16000, chunk_b64=chunk))
        await asyncio.sleep(dt)


@pytest.fixture
async def ink():
    srv = await FakeInk().start()
    yield srv
    await srv.stop()


async def test_no_key_means_apple_from_the_start(h):
    assert h.core.stt.engine == "apple"
    await h.core.on_bus_connect()
    [m] = h.of("stt_mode")
    assert m["engine"] == "apple" and "no CARTESIA_API_KEY" in m["reason"]
    await stream(h, 3)  # mic audio is dropped, nothing is opened
    assert not h.of("transcript")


async def test_cartesia_turns_become_transcripts_and_a_turn(tmp_path, ink):
    h = Harness(stt_settings(tmp_path, ink.url))
    await h.feed(snapshot())
    await stream(h, 4)
    assert await wait_until(lambda: any(m["type"] == "guide_start" for m in h.out))
    await h.core.drain()
    ts = h.of("transcript")
    assert [(t["text"], t["is_final"], t["source"]) for t in ts][-1] == ("Where's the sugar?", True, "cartesia")
    assert ("Where's", False, "cartesia") in [(t["text"], t["is_final"], t["source"]) for t in ts]
    assert h.of("guide_start")[0]["object_id"] == "sugar"
    # credit saving: one socket for the burst, closed with {"type":"close"} after the idle timeout
    assert await wait_until(lambda: ink.got_close == 1, timeout=3)
    assert ink.connections == 1 and ink.audio_bytes >= 4 * 3200
    q = parse_qs(urlparse(ink.paths[0]).query)
    assert q["model"] == ["ink-2"] and q["encoding"] == ["pcm_s16le"] and q["sample_rate"] == ["16000"]
    assert q["cartesia_version"] == ["2026-08-14"] and "sugar" in q["keyterm"] and "Earmark" in q["keyterm"]
    assert ink.auth[0] == "Bearer sk_car_test"
    assert not h.of("stt_mode")
    # a new burst opens a new socket
    await stream(h, 2)
    assert await wait_until(lambda: ink.connections == 2)


async def test_never_connected_falls_back_to_apple_then_recovers(tmp_path, ink):
    ink.mode = "silent"
    h = Harness(stt_settings(tmp_path, ink.url))
    await h.feed(snapshot())
    await stream(h, 25)
    assert await wait_until(lambda: h.of("stt_mode"))
    [m] = h.of("stt_mode")
    assert m["engine"] == "apple" and "not connected" in m["reason"]
    assert await wait_until(lambda: any(x.get("phrase_id") == "stt_fallback" for x in h.out))
    assert h.core.stt.engine == "apple"
    # Apple transcripts are accepted in fallback
    h.clear()
    from earmark_contracts import Transcript
    await h.feed(Transcript(text="Where's the sugar?", is_final=True, source="apple"))
    assert h.of("guide_start")
    # probes fail while the server stays silent, then Cartesia comes back
    await asyncio.sleep(0.5)
    assert h.core.stt.engine == "apple"
    ink.mode = "good"
    assert await wait_until(lambda: h.core.stt.engine == "cartesia", timeout=5)
    assert h.of("stt_mode")[-1]["engine"] == "cartesia"


async def test_no_turn_events_while_audio_flows_falls_back(tmp_path, ink):
    ink.mode = "mute"
    h = Harness(stt_settings(tmp_path, ink.url))
    await h.feed(snapshot())
    await stream(h, 40, chunk=LOUD)
    assert h.of("stt_mode") and "no transcript" in h.of("stt_mode")[0]["reason"]


async def test_silence_while_push_to_talk_is_held_does_not_fall_back(tmp_path, ink):
    ink.mode = "mute"
    h = Harness(stt_settings(tmp_path, ink.url))
    await h.feed(snapshot())
    await stream(h, 40)  # silence streams while the key is held, and no turn ever starts
    assert not h.of("stt_mode") and h.core.stt.engine == "cartesia"


async def test_preconnect_buffer_is_capped_by_time_not_chunk_count(tmp_path):
    from earmark_concierge.stt import CartesiaStt
    s = make_settings(tmp_path, cartesia_api_key="sk_car_test", stt_url="ws://127.0.0.1:1/x")
    stt = CartesiaStt(s, keyterms=lambda: [])
    big = base64.b64encode(bytes(16000 * 2)).decode()  # one 1 s chunk
    for i in range(10):
        await stt.on_mic_audio(MicAudio(seq=i, sample_rate=16000, chunk_b64=big))
    assert stt._burst.queue.qsize() == 3  # 3 s of audio, whatever the chunk size
    stt._burst.task.cancel()

async def test_server_error_falls_back(tmp_path, ink):
    ink.mode = "error"
    h = Harness(stt_settings(tmp_path, ink.url))
    await h.feed(snapshot())
    await stream(h, 5)
    assert await wait_until(lambda: h.of("stt_mode"))
    assert "concurrency_limited" in h.of("stt_mode")[0]["reason"]


async def test_unreachable_server_falls_back(tmp_path):
    h = Harness(stt_settings(tmp_path, "ws://127.0.0.1:9"))
    await h.feed(snapshot())
    await stream(h, 3)
    assert await wait_until(lambda: h.of("stt_mode"))
    assert h.of("stt_mode")[0]["engine"] == "apple"
