"""The hub: adapters and bus clients in, debounced state out to the bus and Convex.

UWB (docs/UWB-PRD.md 8): `uwb_token` is relayed only to its addressee; `uwb_range`, `motion_state`,
`head_pose` and `listener_command` feed the tracker, whether they come from a bus client or an adapter;
NFC `pickup`/`placed` re-anchor a frozen listener. The tracker's `listener_pose` goes to the bus at
`uwb.solve_hz` (and at once on every mode change) and, throttled, to Convex.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from earmark_contracts import (
    Chirp,
    DetectionEvent,
    HeadPose,
    Label,
    LabelRequest,
    ListenerCommand,
    ListenerPose,
    MotionState,
    ObjectState,
    Pickup,
    PickupResult,
    RegistryObject,
    RegistryUpdate,
    Reset,
    Snapshot,
    StatusMsg,
    TrialEnd,
    TrialStart,
    UnknownTag,
    UwbRange,
    UwbToken,
    to_dict,
)
from pydantic import ValidationError

from .adapters.base import Adapter
from .bus import BusServer, Client
from .clock import Clock, SystemClock
from .config import ROOT, ConvexEnv, HubConfig
from .convex import ConvexClient, ConvexSync
from .registry import RegistryStore
from .space import SpaceIndex
from .state import Placed, Removed, StateEngine
from .uwb.relay import TokenRelay
from .uwb.tracker import Tracker

log = logging.getLogger("earmark.hub")

FORWARDED = (TrialStart, TrialEnd, PickupResult, Chirp, UnknownTag, Pickup)
TRACKER_INPUTS = (UwbRange, MotionState, HeadPose, ListenerCommand)
IOS_COMPONENTS = ("ios_wearer", "ios_anchor")


class Hub:
    def __init__(self, cfg: HubConfig, *, clock: Clock | None = None, adapters: list[Adapter] | None = None,
                 convex_env: ConvexEnv | None = None, offline_reason: str = "", root: Path = ROOT,
                 convex_transport=None) -> None:
        self.cfg = cfg
        self.root = root
        self.clock = clock or SystemClock()
        self.adapters = adapters or []
        self.space = SpaceIndex.load(cfg.path("space", root))
        self.relay = TokenRelay()
        self.tracker = Tracker(cfg.uwb, self.space, self.clock.now())
        self.pose: ListenerPose = self.tracker.pose  # latest published listener_pose (fixed at the origin first)
        self.registry = RegistryStore(cfg.path("cache", root), cfg.path("seed", root))
        self.engine = StateEngine(self.space, self.registry.objects, placement_reads=cfg.debounce.placement_reads,
                                  removal_s=cfg.debounce.removal_s)
        self.bus = BusServer(cfg.bus.host, cfg.bus.port, on_message=self._on_client_message,
                             on_hello=self._on_hello, queue_max=cfg.bus.client_queue_max, secret=cfg.bus.secret)
        self.sync: ConvexSync | None = None
        if convex_env is not None:
            client = ConvexClient(convex_env, cfg.convex.timeout_s, transport=convex_transport)
            self.sync = ConvexSync(client, cfg.path("queue", root), cfg.convex, pose_hz=cfg.uwb.convex_pose_hz)
        self.offline_reason = offline_reason
        self._adapter_state: dict[str, tuple[bool, str]] = {a.name: (True, "starting") for a in self.adapters}
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------ HubContext (for adapters)

    def objects(self) -> list[RegistryObject]:
        return self.registry.objects

    async def publish(self, msg, origin: str) -> None:
        await self._dispatch(None, msg, origin)

    def adapter_status(self, adapter: str, ok: bool, detail: str) -> None:
        if self._adapter_state.get(adapter) != (ok, detail):
            (log.info if ok else log.warning)("adapter status", extra={"adapter": adapter, "ok": ok, "detail": detail})
        self._adapter_state[adapter] = (ok, detail)

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        await self.bus.start()
        for a in self.adapters:
            a.attach(self)
            self._tasks.append(asyncio.create_task(self._run_adapter(a), name=f"adapter:{a.name}"))
        self._tasks.append(asyncio.create_task(self._tick_loop(), name="tick"))
        self._tasks.append(asyncio.create_task(self._health_loop(), name="health"))
        self._publish_poses([self.pose])
        if self.cfg.uwb.enabled:
            self._tasks.append(asyncio.create_task(self._uwb_loop(), name="uwb"))
        if self.sync is not None:
            self._tasks.append(asyncio.create_task(self.sync.run(), name="convex-flush"))
            self._tasks.append(asyncio.create_task(self.sync.poll_registry(self._on_remote_registry),
                                                   name="convex-registry"))
        else:
            log.info("Convex sync disabled; running fully offline", extra={"reason": self.offline_reason})
        log.info("hub started", extra={"adapters": [a.name for a in self.adapters], "port": self.bus.port})

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for a in self.adapters:
            try:
                await asyncio.wait_for(a.close(), 5.0)
            except Exception as e:
                log.warning("adapter close failed", extra={"adapter": a.name, "error": str(e)})
        await self.bus.stop()
        if self.sync is not None:
            await self.sync.client.aclose()

    async def _run_adapter(self, adapter: Adapter) -> None:
        backoff = 1.0
        while True:
            try:
                async for ev in adapter.events():
                    self._on_detection(ev, None)
                    backoff = 1.0
                log.info("adapter finished", extra={"adapter": adapter.name})
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("adapter crashed", extra={"adapter": adapter.name})
                self.adapter_status(adapter.name, False, f"crashed ({type(e).__name__}: {e}); restarting")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _tick_loop(self) -> None:
        while True:
            await self.clock.sleep(self.cfg.debounce.tick_s)
            self._apply(self.engine.tick(self.clock.now()))

    async def _uwb_loop(self) -> None:
        period = 1.0 / self.cfg.uwb.solve_hz
        while True:
            await self.clock.sleep(period)
            now = self.clock.now()
            self._publish_poses(self.tracker.tick(now))
            if self.sync is not None:
                self.sync.set_anchors(self.tracker.ingest_anchors(now))

    def _publish_poses(self, poses: list[ListenerPose]) -> None:
        for p in poses:
            self.pose = p
            self.bus.broadcast(p)
            if self.sync is not None:
                self.sync.set_pose(p)

    # ------------------------------------------------------------ inbound

    async def _on_hello(self, client: Client) -> None:
        self.bus.send_to(client, self.snapshot())
        if client.wants("listener_pose"):
            self.bus.send_to(client, self.pose)
        for token in self.relay.addressed_to(client.device_id) if client.device_id else []:
            self.bus.send_to(client, token)

    async def _on_client_message(self, client: Client, msg) -> None:
        await self._dispatch(client, msg)

    async def _dispatch(self, client: Client | None, msg, origin: str | None = None) -> None:
        """Route `msg` to every other subscribed client, then act on it. `client` is None for adapter messages."""
        if isinstance(msg, DetectionEvent):
            self._on_detection(msg, client)
            return
        if isinstance(msg, UwbToken):  # addressed: never broadcast
            self.relay.store(msg)
            n = self.bus.send_to_device(msg.to, msg)
            log.debug("uwb_token relayed", extra={"from": msg.from_, "to": msg.to, "delivered": n})
            return
        self.bus.broadcast(msg, exclude=client)
        if isinstance(msg, TRACKER_INPUTS):
            self._to_tracker(client, msg)
        if isinstance(msg, Label):
            self._label(msg)
        elif isinstance(msg, Reset):
            await self.reset()
        elif isinstance(msg, Chirp):
            await self._chirp(msg)
        if isinstance(msg, FORWARDED):
            self._forward(msg)

    def _to_tracker(self, client: Client | None, msg) -> None:
        if not self.cfg.uwb.enabled:
            return
        now = self.clock.now()
        if isinstance(msg, UwbRange):
            ios = client is not None and client.component in IOS_COMPONENTS
            self.tracker.on_range(msg, now, "uwb" if ios else "sim")
        elif isinstance(msg, MotionState):
            self.tracker.on_motion(msg.state, now)
        elif isinstance(msg, HeadPose):
            self.tracker.on_head_pose(msg.yaw, now)
        else:
            self._publish_poses(self.tracker.on_command(msg.action, now))

    def _on_detection(self, ev: DetectionEvent, client: Client | None) -> None:
        self.bus.broadcast(ev, exclude=client)
        self._apply(self.engine.handle(ev))

    # ------------------------------------------------------------ engine output

    def _apply(self, outputs: list) -> None:
        for o in outputs:
            if isinstance(o, (Placed, Removed)):
                kind = "placed" if isinstance(o, Placed) else "removed"
                log.info(kind, extra={"object_id": o.object_id, "spot": o.spot, "tag": o.tag})
                if self.sync is not None:
                    self.sync.add_event(kind, o.object_id, o.t, {"spot": o.spot, "tag": o.tag, "source": o.source})
                if isinstance(o, Placed):
                    self._publish_poses(self.tracker.on_contact(o.spot, self.clock.now(), "placed"))
                continue
            self.bus.broadcast(o)
            if isinstance(o, ObjectState):
                log.debug("state", extra={"object_id": o.object_id, "status": o.status, "spot": o.location.spot})
                if self.sync is not None:
                    self.sync.add_state(o)
            else:
                log.info(o.type, extra=to_dict(o))
                self._forward(o)
                if isinstance(o, Pickup):
                    self._publish_poses(self.tracker.on_contact(o.from_spot, self.clock.now(), "pickup"))

    def _forward(self, msg) -> None:
        if self.sync is None:
            return
        if isinstance(msg, Pickup):
            oid = msg.object_id
        elif isinstance(msg, PickupResult):
            oid = msg.actual
        elif isinstance(msg, (TrialStart, TrialEnd)):
            oid = msg.target_object_id
        elif isinstance(msg, Chirp):
            obj = self.registry.find_by_fob(msg.fob_id)
            oid = obj.object_id if obj else None
        else:
            oid = None
        self.sync.add_event(msg.type, oid, msg.t, to_dict(msg))

    # ------------------------------------------------------------ actions

    def snapshot(self) -> Snapshot:
        return Snapshot(household=self.registry.registry.household, space=self.space.space,
                        objects=self.registry.objects, states=self.engine.states(),
                        registry_version=self.registry.version, t=self.clock.now())

    async def reset(self) -> None:
        log.info("reset")
        for a in self.adapters:
            try:
                await asyncio.wait_for(a.on_reset(), 3.0)
            except Exception as e:
                log.warning("adapter reset failed", extra={"adapter": a.name, "error": str(e)})
        self.registry.reload()
        try:
            self.space = SpaceIndex.load(self.cfg.path("space", self.root))
        except (OSError, ValueError, ValidationError) as e:
            log.error("space.json not reloaded; keeping the previous layout", extra={"error": str(e)[:300]})
        self.engine.space = self.space
        self.tracker.load_space(self.space)
        now = self.clock.now()
        self._apply(self.engine.reset(self.registry.objects, now=now))
        poses = self.tracker.reset(now)
        snap = self.snapshot()
        for c in list(self.bus.clients):
            self.bus.send_to(c, snap)
        self._publish_poses(poses)  # after the snapshot: clients see reset, snapshot, then listener_pose
        if self.sync is not None:
            self.sync.set_anchors(self.tracker.ingest_anchors(now))

    def _label(self, msg: Label) -> None:
        object_id, created = self.registry.apply_label(msg)
        log.info("label", extra={"object_id": object_id, "created": created, "tag": msg.tag, "name": msg.name})
        self._registry_changed()
        if self.sync is not None:
            self.sync.add_label(LabelRequest(tag=msg.tag, name=msg.name, aliases=msg.aliases, spot=msg.spot))
            self.sync.add_event("label", object_id, msg.t, to_dict(msg))

    async def _chirp(self, msg: Chirp) -> None:
        ble = next((a for a in self.adapters if hasattr(a, "chirp")), None)
        if ble is None:
            log.info("chirp not executed: ble_fobs adapter is not enabled", extra={"fob_id": msg.fob_id})
            return
        await ble.chirp(msg.fob_id, msg.action)

    async def _on_remote_registry(self, reg) -> None:
        if not self.registry.differs(reg):
            return
        log.info("registry updated from convex", extra={"version": reg.version, "objects": len(reg.objects)})
        self.registry.replace(reg)
        for pending in self.sync.pending_labels() if self.sync else []:
            self.registry.apply_label(pending)  # local labels Convex has not acknowledged yet
        self._registry_changed()

    def _registry_changed(self) -> None:
        self.bus.broadcast(RegistryUpdate(objects=self.registry.objects, registry_version=self.registry.version,
                                          t=self.clock.now()))
        self._apply(self.engine.set_objects(self.registry.objects))

    # ------------------------------------------------------------ health

    def health(self) -> StatusMsg:
        adapters_ok = all(ok for ok, _ in self._adapter_state.values())
        if self.sync is None:
            convex = "disabled"
        else:
            convex = {None: "connecting", True: "online", False: "offline"}[self.sync.reachable]
        depth = self.sync.depth if self.sync else 0
        parts = [f"{name}: {detail}" for name, (_, detail) in self._adapter_state.items()]
        parts += [f"convex {convex}", f"queue {depth}", f"{len(self.bus.clients)} clients"]
        info = {
            "adapters": ",".join(f"{n}:{'ok' if ok else 'error'}" for n, (ok, _) in self._adapter_state.items()),
            "convex": convex,
            "queue_depth": depth,
            "clients": len(self.bus.clients),
            "registry_version": self.registry.version,
        }
        return StatusMsg(component="hub", ok=adapters_ok and convex != "offline", detail="; ".join(parts),
                         info=info, t=self.clock.now())

    async def _health_loop(self) -> None:
        last_key, last_sent = None, 0.0
        while True:
            st = self.health()
            key = (st.ok, st.detail, tuple(sorted(st.info.items())))
            now = time.monotonic()
            if key != last_key or now - last_sent >= self.cfg.health.interval_s:
                self.bus.broadcast(st)
                last_key, last_sent = key, now
            await asyncio.sleep(0.25)
