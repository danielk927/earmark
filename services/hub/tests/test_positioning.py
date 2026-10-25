"""Two positioning systems at once: UWB (the hub's tracker) and sound (listener_pose from a bus client: the chirp
ranging service, the beacon locator, a simulator). positioning.active picks the one sent as listener_pose,
`positioning` reports both side by side, and taps are always placed with UWB. In-process hub, real clients."""
from __future__ import annotations

import asyncio
import math

import pytest
from earmark_contracts import ListenerPose, PositioningSelect

from earmark_hub.config import ConvexCfg, ConvexEnv
from earmark_hub.convex import ConvexClient, ConvexSync
from earmark_hub.hub import Hub
from test_uwb_hub import Peer, ranges_from, tap


@pytest.fixture
async def hub(hub_cfg, hub_root):
    h = Hub(hub_cfg, root=hub_root)
    await h.start()
    yield h
    await h.stop()


def sound(x=1.0, y=2.0, quality="ok") -> ListenerPose:
    return ListenerPose(position=[x, y, 1.2], quality=quality, source="beacons", beacons_heard=3, t=1.0)


async def track(h: Hub, wearer: Peer, head=(0.3, -1.6), n=3) -> None:
    for k in range(n):  # fixes accumulate on every solver tick while ranges are fresh
        for r in ranges_from(h.space, head, seq=k):
            await wearer.send(r)
        await asyncio.sleep(0.15)


def poses(msgs, source=None) -> list[ListenerPose]:
    return [m for m in msgs if m.type == "listener_pose" and (source is None or m.source == source)]


def last_positioning(msgs):
    return [m for m in msgs if m.type == "positioning"][-1]


async def test_uwb_drives_by_default_and_sound_poses_show_only_in_positioning(hub):
    mac = await Peer.join(hub, "mac_app", subscribe=["listener_pose", "positioning"])
    ranging = await Peer.join(hub, "locator", subscribe=[])
    await ranging.send(sound())
    got = await mac.drain(0.5)
    assert hub.active == "uwb" and not poses(got, "beacons")
    pos = last_positioning(got)
    assert pos.active == "uwb" and pos.uwb is None and pos.sound.position == [1.0, 2.0, 1.2]
    assert pos.sound.source == "beacons" and pos.sound.mode is None and pos.sound.age_s < 0.5


async def test_selecting_sound_sends_its_latest_pose_at_once_then_forwards_sound_and_not_uwb(hub):
    mac = await Peer.join(hub, "mac_app", subscribe=["listener_pose", "positioning"])
    dash = await Peer.join(hub, "dashboard", subscribe=[])
    ranging = await Peer.join(hub, "locator", subscribe=["listener_pose"])
    wearer = await Peer.join(hub, "ios_wearer", device_id="wearer", subscribe=[])
    await ranging.send(sound(1.0, 2.0))
    await asyncio.sleep(0.1)
    await mac.drain(0.1)
    await dash.send(PositioningSelect(active="sound"))
    first = await mac.next_of("listener_pose")
    assert first.source == "beacons" and first.position == [1.0, 2.0, 1.2]
    assert (await mac.next_of("positioning")).active == "sound"

    await track(hub, wearer)  # UWB tracks too, but no longer drives the audio
    await ranging.drain(0.1)
    await ranging.send(sound(1.5, 2.5))
    got = await mac.drain(0.4)
    assert poses(got, "beacons")[-1].position == [1.5, 2.5, 1.2]
    assert not poses(got, "uwb")
    assert last_positioning(got).uwb.mode == "tracked"
    assert not poses(await ranging.drain(0.2), "beacons")  # the sender never gets its own pose back


async def test_back_to_uwb_sends_the_tracker_pose_at_once(hub):
    hub.active = "sound"
    mac = await Peer.join(hub, "mac_app", subscribe=["listener_pose"])
    wearer = await Peer.join(hub, "ios_wearer", device_id="wearer", subscribe=[])
    await track(hub, wearer)
    assert not poses(await mac.drain(0.2), "uwb")
    await mac.send(PositioningSelect(active="uwb"))
    p = await mac.next_of("listener_pose")
    assert p.source == "uwb" and p.mode == "tracked" and p.quality == "ok"


async def test_selecting_sound_with_no_sound_pose_yet_says_lost(hub):
    mac = await Peer.join(hub, "mac_app", subscribe=["listener_pose"])
    await mac.drain(0.1)
    await mac.send(PositioningSelect(active="sound"))
    p = await mac.next_of("listener_pose")
    assert p.quality == "lost" and p.source == "none"


async def test_a_sound_source_that_goes_silent_turns_lost_once_where_it_was(hub):
    hub.active = "sound"
    mac = await Peer.join(hub, "mac_app", subscribe=["listener_pose"])
    ranging = await Peer.join(hub, "locator", subscribe=[])
    await ranging.send(sound())
    assert (await mac.next_of("listener_pose", lambda m: m.source == "beacons")).quality == "ok"
    hub.sound_pose_rx -= hub.cfg.positioning.sound_fresh_s + 1  # nothing heard for longer than sound_fresh_s
    lost = await mac.next_of("listener_pose", lambda m: m.quality == "lost", timeout=1.0)
    assert lost.position == [1.0, 2.0, 1.2] and lost.source == "beacons"
    assert not [m for m in poses(await mac.drain(0.5)) if m.quality == "lost"]  # said once


async def test_positioning_comes_on_hello_and_stays_quiet_while_nothing_tracks(hub):
    dash = await Peer.join(hub, "dashboard")
    pos = [m for m in await dash.drain(0.6) if m.type == "positioning"]
    assert len(pos) == 1 and pos[0].uwb is None and pos[0].sound is None


@pytest.mark.parametrize("active", ["uwb", "sound"])
async def test_taps_are_uwb_only_whichever_system_drives_the_audio(hub, active):
    hub.active = active
    listener = await Peer.join(hub, "cli", subscribe=["tap_position"])
    ranging = await Peer.join(hub, "locator", subscribe=[])
    wearer = await Peer.join(hub, "ios_wearer", device_id="wearer", subscribe=[])
    await ranging.send(sound())
    await asyncio.sleep(0.1)
    none = await tap(listener, wearer)
    assert none.ok is False and none.position is None and none.source == "none"  # a fresh sound pose is not used
    head = (0.3, -1.6)
    await track(hub, wearer, head)
    got = await tap(listener, wearer)
    assert got.ok and got.source == "uwb" and got.position[2] == 0.9
    assert math.dist(got.position[:2], (head[0], head[1] + 0.2)) < 0.02  # the phone, 0.2 m in front of the head


def test_health_reports_the_active_system(hub_cfg, hub_root):
    hub_cfg.positioning.active = "sound"
    assert Hub(hub_cfg, root=hub_root).health().info["positioning"] == "sound"


@pytest.mark.parametrize(("quality", "mode"), [("ok", "tracked"), ("degraded", "tracked"), ("lost", "lost")])
def test_sound_poses_reach_convex_as_sound_with_a_mode(tmp_path, quality, mode):
    sync = ConvexSync(ConvexClient(ConvexEnv("http://127.0.0.1:9", "x"), 1.0), tmp_path / "q.jsonl", ConvexCfg())
    sync.set_pose(sound(quality=quality))
    assert (sync._pose.source, sync._pose.mode) == ("sound", mode)
    sync.set_pose(ListenerPose(position=[0, 0, 1.55], quality="ok", source="uwb", mode="frozen"))
    assert (sync._pose.source, sync._pose.mode) == ("uwb", "frozen")
