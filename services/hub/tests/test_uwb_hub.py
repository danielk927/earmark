"""UWB in the hub (docs/project/UWB-PRD.md 8, 9.4): token relay, bus auth for the iPhones, NFC re-anchor through the
state engine, and listener_pose on the bus. In-process hub with real WebSocket clients, real clock."""
from __future__ import annotations

import asyncio
import logging
import math
import time

import pytest
from earmark_contracts import (
    DetectionEvent,
    Hello,
    ListenerCommand,
    ListenerPose,
    MotionState,
    ObjectTap,
    Reset,
    Snapshot,
    UwbRange,
    UwbToken,
    dump,
    parse_bus,
)
from websockets.asyncio.client import connect

from conftest import SUGAR
from earmark_hub.bus import Client, auth_error, is_loopback
from earmark_hub.config import UwbSimCfg
from earmark_hub.hub import Hub
from earmark_hub.uwb.sim import UwbSimAdapter


@pytest.fixture
async def hub(hub_cfg, hub_root):
    h = Hub(hub_cfg, root=hub_root)
    await h.start()
    yield h
    await h.stop()


class Peer:
    """A raw bus client that can say hello with a device_id (BusClient cannot)."""

    def __init__(self, ws, snapshot):
        self.ws, self.snapshot = ws, snapshot

    @classmethod
    async def join(cls, h: Hub, component: str, device_id: str | None = None, subscribe=None, role=None):
        ws = await connect(f"ws://127.0.0.1:{h.bus.port}")
        kw = {k: v for k, v in (("device_id", device_id), ("subscribe", subscribe), ("role", role)) if v is not None}
        await ws.send(dump(Hello(component=component, **kw)))
        async with asyncio.timeout(3):
            while not isinstance(msg := parse_bus(await ws.recv()), Snapshot):
                pass
        return cls(ws, msg)

    async def send(self, msg):
        await self.ws.send(dump(msg))

    async def recv(self):
        return parse_bus(await self.ws.recv())

    async def drain(self, seconds=0.3):
        got = []
        try:
            async with asyncio.timeout(seconds):
                while True:
                    got.append(await self.recv())
        except TimeoutError:
            pass
        return got

    async def next_of(self, msg_type, pred=lambda m: True, timeout=3.0):
        async with asyncio.timeout(timeout):
            while True:
                msg = await self.recv()
                if msg.type == msg_type and pred(msg):
                    return msg

    async def close(self):
        await self.ws.close()


def token(frm, to, b64="QUJD"):
    return UwbToken(**{"from": frm}, to=to, token_b64=b64)


def ranges_from(space, head, phone_z=1.2, offset=0.2, seq=0):  # space.json: ear_z_m 1.55 + phone_z -0.35
    """Wearer ranges to every anchor for a head at `head` facing the counter (phone `offset` m in front)."""
    phone = (head[0], head[1] + offset, phone_z)
    return [UwbRange(anchor=a.anchor, distance_m=round(math.dist(phone, a.position), 4), seq=seq)
            for a in space.space.anchors]


# ---------------------------------------------------------------- token relay


async def test_uwb_token_goes_only_to_its_addressee(hub):
    anchor = await Peer.join(hub, "ios_anchor", device_id="uwb_1", role="anchor", subscribe=[])
    other = await Peer.join(hub, "ios_anchor", device_id="uwb_2", role="anchor")
    wearer = await Peer.join(hub, "ios_wearer", device_id="wearer", role="wearer")
    everything = await Peer.join(hub, "cli", subscribe=["*"])
    await wearer.send(token("wearer", "uwb_1"))
    got = await anchor.next_of("uwb_token")  # addressed delivery ignores subscriptions
    assert (got.from_, got.to, got.token_b64) == ("wearer", "uwb_1", "QUJD")
    for peer in (other, wearer, everything):
        assert not any(m.type == "uwb_token" for m in await peer.drain(0.3))
    for p in (anchor, other, wearer, everything):
        await p.close()


async def test_latest_token_is_replayed_on_hello_and_survives_reset(hub):
    wearer = await Peer.join(hub, "ios_wearer", device_id="wearer")
    await wearer.send(token("wearer", "uwb_1", "b2xk"))
    await wearer.send(token("wearer", "uwb_1", "bmV3"))  # replaces the first for (wearer, uwb_1)
    await wearer.send(token("wearer", "uwb_2", "dHdv"))
    await wearer.send(token("uwb_1", "wearer", "YmFjaw=="))
    await wearer.send(Reset())  # "on reset, clear nothing"
    await wearer.next_of("snapshot")
    late = await Peer.join(hub, "ios_anchor", device_id="uwb_1")  # anchor app (re)connects
    got = [m for m in await late.drain(0.3) if m.type == "uwb_token"]
    assert [(m.from_, m.to, m.token_b64) for m in got] == [("wearer", "uwb_1", "bmV3")]
    nobody = await Peer.join(hub, "ios_anchor")  # no device_id: nothing addressed to it
    assert not any(m.type == "uwb_token" for m in await nobody.drain(0.3))
    for p in (wearer, late, nobody):
        await p.close()


# ---------------------------------------------------------------- auth (bus leaves localhost)


class FakeWs:
    """A connection from the LAN: what the bus sees for an iPhone."""

    def __init__(self, host="192.168.1.20"):
        self.remote_address = (host, 50123)
        self.sent: list[str] = []
        self.closed: int | None = None

    async def send(self, text):
        self.sent.append(text)

    async def close(self, code=1000, reason=""):
        self.closed = code


def test_auth_check():
    assert auth_error(None, None, None) is None  # in-process
    for host in ("127.0.0.1", "127.8.8.8", "::1", "::ffff:127.0.0.1", "localhost"):
        assert is_loopback(host) and auth_error(host, None, None) is None
    assert "no bus secret" in auth_error("192.168.1.20", "s3cret", None)
    assert auth_error("192.168.1.20", None, "s3cret") == "wrong or missing bus secret in hello"
    assert auth_error("192.168.1.20", "nope", "s3cret") == "wrong or missing bus secret in hello"
    assert auth_error("192.168.1.20", "s3cret", "s3cret") is None
    assert auth_error("fe80::1%en0", "s3cret", "s3cret") is None


@pytest.mark.parametrize("sent", [None, "wrong"])
async def test_lan_client_without_the_secret_is_refused(hub_cfg, hub_root, caplog, sent):
    hub_cfg.bus.secret = "s3cret"
    h = Hub(hub_cfg, root=hub_root)
    ws = FakeWs()
    c = Client(ws, 100)
    assert not c.authorized
    h.bus.clients.add(c)
    hello = Hello(component="ios_wearer", device_id="wearer", **({"secret": sent} if sent else {}))
    with caplog.at_level(logging.DEBUG):
        await h.bus._receive(c, dump(hello))
        h.bus.broadcast(MotionState(state="still"))
        assert h.bus.send_to_device("wearer", token("uwb_1", "wearer")) == 0
    status = parse_bus(ws.sent[0])
    assert status.type == "status" and status.ok is False and "secret" in status.detail
    assert ws.closed == 1008 and not c.authorized and c.device_id is None and len(c.queue) == 0
    assert "s3cret" not in caplog.text and (sent is None or sent not in caplog.text)


async def test_lan_client_cannot_send_before_hello(hub_cfg, hub_root):
    hub_cfg.bus.secret = "s3cret"
    h = Hub(hub_cfg, root=hub_root)
    ws = FakeWs()
    c = Client(ws, 100)
    await h.bus._receive(c, dump(ranges_from(h.space, (0.0, -1.0))[0]))
    assert ws.closed == 1008 and h.tracker.ranges == {}


async def test_lan_client_with_the_secret_is_admitted_and_gets_its_tokens(hub_cfg, hub_root, caplog):
    hub_cfg.bus.secret = "s3cret"
    h = Hub(hub_cfg, root=hub_root)
    h.relay.store(token("uwb_1", "wearer", "dG9rZW4="))
    ws = FakeWs()
    c = Client(ws, 100)
    h.bus.clients.add(c)
    with caplog.at_level(logging.DEBUG):
        await h.bus._receive(c, dump(Hello(component="ios_wearer", device_id="wearer", role="wearer", secret="s3cret")))
    assert c.authorized and c.device_id == "wearer" and ws.closed is None
    queued = [parse_bus(text) for _, text in c.queue._items]
    assert [m.type for m in queued] == ["snapshot", "listener_pose", "uwb_token"]
    assert queued[2].token_b64 == "dG9rZW4="
    assert "s3cret" not in caplog.text
    await h.bus._receive(c, dump(ranges_from(h.space, (0.0, -1.0))[0]))
    assert set(h.tracker.ranges) == {"uwb_1"} and h.tracker.source == "uwb"  # ios_wearer ranges are real UWB


async def test_no_secret_configured_refuses_every_lan_client(hub_cfg, hub_root):
    h = Hub(hub_cfg, root=hub_root)
    ws = FakeWs("10.0.0.7")
    c = Client(ws, 100)
    await h.bus._receive(c, dump(Hello(component="ios_wearer", device_id="wearer", secret="anything")))
    assert ws.closed == 1008 and "EARMARK_BUS_SECRET" in parse_bus(ws.sent[0]).detail


# ---------------------------------------------------------------- listener_pose and NFC re-anchor


async def test_listener_pose_on_the_bus(hub):
    dash = await Peer.join(hub, "dashboard", subscribe=["listener_pose"])
    first = await dash.next_of("listener_pose")
    assert first.mode == "fixed" and first.position == [0.0, 0.0, 0.0] and first.source == "none"
    wearer = await Peer.join(hub, "ios_wearer", device_id="wearer", subscribe=[])
    head = (0.3, -1.6)
    start = time.monotonic()
    for k in range(10):  # 1 s of ranges at 10 Hz
        for r in ranges_from(hub.space, head, seq=k):
            await wearer.send(r)
        await asyncio.sleep(0.1)
    poses = [m for m in await dash.drain(0.1) if m.type == "listener_pose"]
    elapsed = time.monotonic() - start
    tracked = [p for p in poses if p.mode == "tracked"]
    assert len(tracked) >= 5 * elapsed * 0.8  # ~10 Hz while ranged (>= 5 Hz with slack for a loaded CI box)
    last = tracked[-1]
    assert math.dist(last.position[:2], head) < 0.01 and last.source == "uwb" and last.anchors_used == 3
    assert [a.anchor for a in last.anchors] == ["uwb_1", "uwb_2", "uwb_3"] and all(a.online for a in last.anchors)
    assert hub.pose.mode == "tracked"
    late = await Peer.join(hub, "dashboard", subscribe=["listener_pose"])  # a late joiner gets the latest pose
    assert (await late.next_of("listener_pose")).mode in ("tracked", "lost")
    for p in (dash, wearer, late):
        await p.close()


async def test_ranges_from_a_non_ios_client_are_sim(hub):
    sim = await Peer.join(hub, "cli", subscribe=["listener_pose"])
    for r in ranges_from(hub.space, (0.0, -1.0)):
        await sim.send(r)
    pose = await sim.next_of("listener_pose", lambda m: m.mode == "tracked")
    assert pose.source == "sim"
    await sim.close()


async def test_pickup_through_the_engine_reanchors_a_frozen_listener(hub):
    listener = await Peer.join(hub, "mac_app", subscribe=["listener_pose", "pickup", "state_update"])
    wearer = await Peer.join(hub, "ios_wearer", device_id="wearer", subscribe=[])
    head = (0.9, -0.6)  # stopped off to the right of the counter
    spot3 = hub.space.spot_position(3)[:2]
    assert math.dist(head, spot3) > 0.75

    async def range_once(seq):
        await wearer.send(MotionState(state="still"))
        for r in ranges_from(hub.space, head, seq=seq):
            await wearer.send(r)

    await range_once(0)
    await listener.next_of("listener_pose", lambda m: m.mode == "tracked")
    # Sugar placed on spot 3 while tracked: never re-anchors.
    t = time.time()
    for k in range(2):
        await wearer.send(DetectionEvent(source="nfc", tag=SUGAR, kind="seen", where={"spot": 3}, precision="exact",
                                         rssi=None, t=t + k * 0.5))
    await listener.next_of("state_update", lambda m: m.status == "on_spot")
    await range_once(1)
    pose = await listener.next_of("listener_pose", lambda m: m.t > t)
    assert pose.mode == "tracked" and math.dist(pose.position[:2], head) < 0.01
    # "I'm here": frozen where the user stands.
    await wearer.send(ListenerCommand(action="freeze"))
    frozen = await listener.next_of("listener_pose", lambda m: m.mode == "frozen")
    assert math.dist(frozen.position[:2], head) < 0.01
    # Lifting the sugar (NFC pickup from spot 3) pulls the listener to exactly reach_max_m from spot 3.
    for k in range(4):
        await wearer.send(DetectionEvent(source="nfc", tag="EMPTY", kind="removed", where={"spot": 3},
                                         precision="exact", rssi=None, t=t + 1.0 + k * 0.5))
    pickup = await listener.next_of("pickup")
    assert (pickup.object_id, pickup.from_spot) == ("sugar", 3)
    moved = await listener.next_of("listener_pose", lambda m: math.dist(m.position[:2], head) > 0.05)
    assert moved.mode == "frozen"
    assert math.dist(moved.position[:2], spot3) == pytest.approx(0.75, abs=2e-3)
    assert hub.tracker.mode == "frozen" and math.dist(hub.tracker.position, spot3) == pytest.approx(0.75)
    await listener.close()
    await wearer.close()


async def test_uwb_disabled_keeps_the_listener_fixed(hub_cfg, hub_root):
    hub_cfg.uwb.enabled = False
    h = Hub(hub_cfg, root=hub_root)
    await h.start()
    try:
        wearer = await Peer.join(h, "ios_wearer", device_id="wearer", subscribe=["listener_pose"])
        for r in ranges_from(h.space, (0.0, -1.0)):
            await wearer.send(r)
        await wearer.send(ListenerCommand(action="freeze"))
        poses = [m for m in await wearer.drain(0.4) if m.type == "listener_pose"]
        assert all(p.mode == "fixed" for p in poses) and h.tracker.ranges == {} and h.pose.mode == "fixed"
        await wearer.close()
    finally:
        await h.stop()


async def test_reset_publishes_a_fixed_pose_after_the_snapshot(hub):
    wearer = await Peer.join(hub, "ios_wearer", device_id="wearer", subscribe=["listener_pose", "reset"])
    for r in ranges_from(hub.space, (0.0, -1.0)):
        await wearer.send(r)
    await wearer.next_of("listener_pose", lambda m: m.mode == "tracked")
    other = await Peer.join(hub, "cli", subscribe=["listener_pose", "reset"])
    await other.send(Reset())
    seen = []
    async with asyncio.timeout(3):
        while not (seen and seen[-1].type == "listener_pose" and seen[-1].mode == "fixed"):
            m = await wearer.recv()
            if m.type in ("reset", "snapshot") or (m.type == "listener_pose" and m.mode == "fixed"):
                seen.append(m)
    assert [m.type for m in seen] == ["reset", "snapshot", "listener_pose"]
    assert hub.tracker.mode == "fixed" and hub.tracker.ranges == {}
    await wearer.close()
    await other.close()


# ---------------------------------------------------------------- tap-to-mark


async def tap(listener, tapper):
    await tapper.send(ObjectTap())
    return await listener.next_of("tap_position")


async def test_tap_while_tracking_marks_the_mean_phone_position_at_mark_z(hub):
    listener = await Peer.join(hub, "cli", subscribe=["tap_position"])
    wearer = await Peer.join(hub, "ios_wearer", device_id="wearer", subscribe=[])
    head = (0.3, -1.6)
    for k in range(3):  # fixes accumulate on every solver tick while ranges are fresh
        for r in ranges_from(hub.space, head, seq=k):
            await wearer.send(r)
        await asyncio.sleep(0.15)
    got = await tap(listener, wearer)
    assert got.ok and got.source == "uwb"
    assert got.position[2] == 0.9  # space.json tracking.mark_z_m
    assert math.dist(got.position[:2], (head[0], head[1] + 0.2)) < 0.02  # the phone, 0.2 m in front of the head
    await listener.close()
    await wearer.close()


async def test_tap_with_no_tracker_and_no_beacon_pose_fails(hub):
    listener = await Peer.join(hub, "cli", subscribe=["tap_position"])
    got = await tap(listener, listener)
    assert (got.ok, got.position, got.source) == (False, None, "none")
    await listener.close()


async def test_tap_with_too_few_fixes_falls_through(hub):
    listener = await Peer.join(hub, "cli", subscribe=["tap_position"])
    for r in ranges_from(hub.space, (0.0, -1.0)):
        await listener.send(r)
    await asyncio.sleep(0.12)  # one or two solver ticks: fewer fixes than mark_min_fixes
    hub.cfg.uwb.mark_min_fixes = 50  # ponytail: simpler than racing the tick for a low fix count
    got = await tap(listener, listener)
    assert got.ok is False and got.source == "none"
    await listener.close()


@pytest.mark.parametrize("uwb_enabled", [True, False])
async def test_tap_falls_back_to_a_fresh_beacon_pose(hub_cfg, hub_root, uwb_enabled):
    hub_cfg.uwb.enabled = uwb_enabled
    h = Hub(hub_cfg, root=hub_root)
    await h.start()
    try:
        locator = await Peer.join(h, "locator", subscribe=["tap_position"])
        # The phone's own clock is ancient; only the hub's receive time counts.
        await locator.send(ListenerPose(position=[1.0, 2.0, 1.1], quality="degraded", source="beacons",
                                        beacons_heard=3, t=1.0))
        got = await tap(locator, locator)
        assert got.ok and got.position == [1.0, 2.0, 1.1] and got.source == "beacons"
        h.client_pose_rx -= h.cfg.uwb.beacon_fresh_s + 1  # now stale
        stale = await tap(locator, locator)
        assert stale.ok is False and stale.position is None and stale.source == "none"
        await locator.send(ListenerPose(position=[1.0, 2.0, 1.1], quality="lost", source="beacons", t=1.0))
        assert (await tap(locator, locator)).ok is False  # a lost pose is no position
        await locator.close()
    finally:
        await h.stop()


async def test_sim_m_key_produces_a_tap_position(hub):
    listener = await Peer.join(hub, "cli", subscribe=["tap_position"])
    adapter = UwbSimAdapter(hub.clock, UwbSimCfg(), hub.cfg.uwb, interactive=True, out=lambda s: None)
    adapter.attach(hub)
    assert await adapter.key("m")
    got = await listener.next_of("tap_position")
    assert got.ok is False and got.source == "none"  # nothing tracking in this fixture
    await listener.close()
