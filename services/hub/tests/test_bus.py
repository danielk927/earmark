"""Bus server over real WebSockets: hello/snapshot, routing, validation, reset, labels, chirp, slow clients."""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from earmark_contracts import (
    Chirp,
    DetectionEvent,
    Label,
    MicAudio,
    Registry,
    Reset,
    Snapshot,
    StatusMsg,
    Transcript,
    dump,
)
from websockets.asyncio.client import connect

from conftest import SUGAR, UNKNOWN
from earmark_hub.adapters.base import Adapter
from earmark_hub.bus import Client, SendQueue
from earmark_hub.client import BusClient
from earmark_hub.hub import Hub


@pytest.fixture
async def hub(hub_cfg, hub_root):
    h = Hub(hub_cfg, root=hub_root)
    await h.start()
    yield h
    await h.stop()


def url(h: Hub) -> str:
    return f"ws://127.0.0.1:{h.bus.port}"


async def connect_client(h, component="cli", subscribe=None):
    return await BusClient.connect(component, subscribe=subscribe, url=url(h))


async def drain(client, seconds=0.3, skip=("status",)):
    """Every message received within `seconds`, minus hub status heartbeats."""
    got = []
    try:
        async with asyncio.timeout(seconds):
            while True:
                msg = await client.recv()
                if msg.type not in skip:
                    got.append(msg)
    except TimeoutError:
        pass
    return got


async def next_of(client, msg_type, timeout=2.0):
    async with asyncio.timeout(timeout):
        while True:
            msg = await client.recv()
            if msg.type == msg_type:
                return msg


async def test_hello_gets_snapshot(hub):
    c = await connect_client(hub)
    snap = c.snapshot
    assert isinstance(snap, Snapshot)
    assert [s.spot for s in snap.space.spots] == [1, 2, 3, 4]
    assert {o.object_id for o in snap.objects} == {"salt", "sugar", "pepper", "bp_meds", "keys"}
    assert {s.object_id: s.status for s in snap.states} == dict.fromkeys(
        ["salt", "sugar", "pepper", "bp_meds", "keys"], "missing")
    assert snap.registry_version is None
    await c.close()


async def test_routing_respects_subscriptions(hub):
    sender = await connect_client(hub, "mac_app", subscribe=[])
    concierge = await connect_client(hub, "concierge", subscribe=["mic_audio"])
    dashboard = await connect_client(hub, "dashboard")  # default: everything but audio
    everything = await connect_client(hub, "cli", subscribe=["*"])
    await sender.send(MicAudio(seq=0, sample_rate=16000, chunk_b64="AAAA"))
    await sender.send(Transcript(text="where's the sugar", is_final=True, source="apple"))
    got_concierge = await drain(concierge)
    got_dashboard = await drain(dashboard)
    got_all = await drain(everything)
    got_sender = await drain(sender, skip=())
    assert [m.type for m in got_concierge] == ["mic_audio"]
    assert [m.type for m in got_dashboard] == ["transcript"]
    assert [m.type for m in got_all] == ["mic_audio", "transcript"]
    assert got_sender == []  # never echoed back, and subscribe=[] receives nothing
    for c in (sender, concierge, dashboard, everything):
        await c.close()


async def test_invalid_messages_are_dropped_with_status(hub):
    listener = await connect_client(hub)
    async with connect(url(hub)) as raw:
        await raw.send('{"type":"hello","component":"cli","t":1}')
        await raw.recv()  # snapshot
        await raw.send('{"type":"pickup","object_id":"sugar"}')  # missing fields
        await raw.send("not json")
        await raw.send('{"type":"teleport","t":1}')
        statuses = []
        async with asyncio.timeout(3):
            while len(statuses) < 1:
                msg = await listener.recv()
                if isinstance(msg, StatusMsg) and "invalid message" in msg.detail:
                    statuses.append(msg)
    assert statuses[0].ok is False and statuses[0].component == "hub"
    rest = await drain(listener, 0.3)
    assert not any(m.type == "pickup" for m in rest)
    await listener.close()


async def test_message_before_hello_uses_default_subscription(hub):
    listener = await connect_client(hub)
    async with connect(url(hub)) as raw:
        await raw.send(dump(Transcript(text="hi", is_final=True, source="typed")))
        msg = await next_of(listener, "transcript")
        assert msg.text == "hi"
    await listener.close()


async def test_reset_rebroadcasts_and_sends_fresh_snapshots(hub):
    a = await connect_client(hub)
    b = await connect_client(hub)
    t = time.time()
    for k in range(2):
        await a.send(DetectionEvent(source="simulator", tag=SUGAR, kind="seen", where={"spot": 3},
                                    precision="exact", rssi=None, t=t + k * 0.5))
    state = await next_of(b, "state_update")
    assert state.object_id == "sugar" and state.status == "on_spot"
    await a.send(Reset())
    assert (await next_of(b, "reset")).type == "reset"
    snap_b = await next_of(b, "snapshot")
    snap_a = await next_of(a, "snapshot")
    for snap in (snap_a, snap_b):
        assert {s.object_id: s.status for s in snap.states}["sugar"] == "missing"
    await a.close()
    await b.close()


async def test_reset_reloads_space_json(hub, hub_root):
    path = hub_root / "config" / "space.json"
    data = json.loads(path.read_text())
    data["spots"][0]["position"] = [9.0, 9.0, 9.0]
    path.write_text(json.dumps(data))
    a = await connect_client(hub)
    await a.send(Reset())
    snap = await next_of(a, "snapshot")
    assert snap.space.spots[0].position == [9.0, 9.0, 9.0]
    assert hub.space.spot_position(data["spots"][0]["spot"]) == [9.0, 9.0, 9.0]
    await a.close()


async def test_client_detections_drive_the_engine(hub):
    sim = await connect_client(hub, "simulator", subscribe=[])
    listener = await connect_client(hub, subscribe=["pickup", "state_update", "detection"])
    t = time.time()
    reads = [(SUGAR, 0.0), (SUGAR, 0.5)] + [("EMPTY", 1.0 + k * 0.5) for k in range(4)]
    for tag, dt in reads:
        kind = "removed" if tag == "EMPTY" else "seen"
        await sim.send(DetectionEvent(source="simulator", tag=tag, kind=kind, where={"spot": 3}, precision="exact",
                                      rssi=None, t=t + dt))
    got = await drain(listener, 0.5)
    assert [m.type for m in got].count("detection") == len(reads)
    assert [(m.object_id, m.from_spot) for m in got if m.type == "pickup"] == [("sugar", 3)]
    assert [m.status for m in got if m.type == "state_update"] == ["on_spot", "held"]
    await sim.close()
    await listener.close()


async def test_label_updates_registry_and_cache(hub, hub_root):
    a = await connect_client(hub, "concierge", subscribe=[])
    listener = await connect_client(hub, subscribe=["registry_update", "label", "state_update", "unknown_tag"])
    t = time.time()
    for k in range(2):
        await a.send(DetectionEvent(source="simulator", tag=UNKNOWN, kind="seen", where={"spot": 1},
                                    precision="exact", rssi=None, t=t + k * 0.5))
    unknown = await next_of(listener, "unknown_tag")
    assert unknown.tag == UNKNOWN and unknown.spot == 1
    await a.send(Label(tag=UNKNOWN, name="Honey", aliases=["honey jar"], spot=1))
    assert (await next_of(listener, "label")).name == "Honey"
    update = await next_of(listener, "registry_update")
    honey = next(o for o in update.objects if o.object_id == "honey")
    assert honey.tag == UNKNOWN and honey.home_spot == 1
    state = await next_of(listener, "state_update")
    assert state.object_id == "honey" and state.status == "on_spot" and state.location.spot == 1
    cache = Registry.model_validate_json((hub_root / "config" / "objects.cache.json").read_text())
    assert "honey" in {o.object_id for o in cache.objects}
    await a.close()
    await listener.close()


class FakeBle(Adapter):
    name = "ble_fobs"

    def __init__(self):
        self.calls = []
        self.resets = 0

    async def events(self):
        await asyncio.Event().wait()
        yield  # pragma: no cover

    async def chirp(self, fob_id, action):
        self.calls.append((fob_id, action))

    async def on_reset(self):
        self.resets += 1


async def test_chirp_goes_to_the_ble_adapter_and_reset_stops_it(hub_cfg, hub_root):
    ble = FakeBle()
    h = Hub(hub_cfg, root=hub_root, adapters=[ble])
    await h.start()
    try:
        c = await connect_client(h, "concierge")
        await c.send(Chirp(fob_id="fob_keys", action="start"))
        await c.send(Reset())
        await next_of(c, "snapshot")
        assert ble.calls == [("fob_keys", "start")] and ble.resets == 1
        await c.close()
    finally:
        await h.stop()


async def test_health_status_reports_clients(hub):
    c = await connect_client(hub, subscribe=["status"])
    st = await next_of(c, "status")
    assert st.component == "hub" and st.info["convex"] == "disabled" and st.info["clients"] >= 1
    assert "queue_depth" in st.info
    await c.close()


def test_send_queue_drops_oldest_audio_first():
    q = SendQueue(maxsize=3)
    q.put("state_update", "s1")
    q.put("speak", "a1")
    q.put("speak", "a2")
    q.put("pickup", "p1")  # full: drops a1
    assert [t for _, t in q._items] == ["s1", "a2", "p1"]
    q.put("pickup", "p2")  # drops a2
    q.put("pickup", "p3")  # no audio left: drops the oldest (s1)
    assert [t for _, t in q._items] == ["p1", "p2", "p3"] and q.dropped == 3


async def test_slow_client_never_blocks_others(hub):
    stuck = Client(ws=None, queue_max=10)  # never drained
    hub.bus.clients.add(stuck)
    fast = await connect_client(hub, subscribe=["transcript"])
    sender = await connect_client(hub, "cli", subscribe=[])
    for k in range(50):
        await sender.send(Transcript(text=f"m{k}", is_final=True, source="typed"))
    got = await drain(fast, 0.5)
    assert len(got) == 50 and len(stuck.queue) == 10 and stuck.queue.dropped > 0
    hub.bus.clients.discard(stuck)
    await fast.close()
    await sender.close()


async def test_locator_messages_exactly_as_the_phone_app_sends_them(hub):
    """The locator's own example payloads: no timestamps on hello/status/mic_audio, a token on hello."""
    import json
    from pathlib import Path

    examples = Path(__file__).resolve().parents[3] / "locator" / "contracts" / "examples"
    listener = await connect_client(hub, "mac_app", subscribe=["listener_pose", "mic_audio", "status", "ptt"])
    async with connect(url(hub)) as raw:
        await raw.send(json.dumps({"type": "hello", "component": "locator", "token": "secret"}))
        for name in ("listener_pose.ok", "listener_pose.lost", "status.healthy", "mic_audio.chunk", "ptt.start"):
            await raw.send((examples / f"{name}.json").read_text())
        got = await drain(listener, skip=())
    types = [m.type for m in got]
    assert types.count("listener_pose") == 2 and "mic_audio" in types and "ptt" in types
    assert not [m for m in got if m.type == "status" and not m.ok], "the hub must not reject locator messages"
    await listener.close()
