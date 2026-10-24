"""The concierge core: inbound bus messages -> world updates, turns, and outbound bus messages.

Pure of I/O except through injected collaborators (emit, resolver, router,
speaker, stt), so tests drive it directly without a bus.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from earmark_contracts import (
    Chirp, GuideFeedback, GuideStart, GuideStop, HeadPose, Label, ListenerPose, MicAudio, ObjectState, Pickup,
    PickupResult, PlaceItem, Playback, RegistryObject, RegistryUpdate, Reset, Snapshot, StatusMsg, SttMode,
    Transcript, TrialEnd, TrialStart, UnknownTag,
)

from . import grammar, policy
from .config import Settings
from .intent import Decision, IntentRouter
from .latency import LatencyLog
from .policy import GuideTarget, Plan
from .resolver import Resolver
from .speech import Speaker
from .stt import CartesiaStt
from .tools import ToolCall
from .world import World

log = logging.getLogger(__name__)
PRONOUNS = {"it", "them", "that", "this", "that one", "this one", "those", "they"}
ADVICE = re.compile(r"\b(?:should i|can i|is it (?:ok|okay|safe)|how (?:many|much)|dose|dosage|double|"
                    r"skip|too many|overdose)\b")


@dataclass
class Guiding:
    object_id: str
    name: str
    position: list[float]
    utterance_id: str
    started_t: float


@dataclass
class Pending:
    object_ids: list[str]
    tool: str
    t: float


Emit = Callable[[object], Awaitable[None]]


class Concierge:
    def __init__(self, settings: Settings, world: World, resolver: Resolver, router: IntentRouter,
                 speaker: Speaker, stt: CartesiaStt, latency: LatencyLog, emit: Emit) -> None:
        self.s = settings
        self.world = world
        self.resolver = resolver
        self.router = router
        self.speaker = speaker
        self.stt = stt
        self.latency = latency
        self.emit = emit
        stt.listener = self
        speaker.on_mode_change = lambda: self.spawn(self.publish_status(only_if_changed=True))
        self.started_t = time.time()
        self.ready = asyncio.Event()
        self.mac_present = asyncio.Event()
        self.guiding: Guiding | None = None
        self.chirping: dict[str, float] = {}
        self.pending: Pending | None = None
        self.silent_trial: str | None = None
        self.last_object: str | None = None
        self.last_decision: Decision | None = None
        self._mac_seen: float | None = None
        self._last_behind = 0.0
        self._guide_timer: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._turn_lock = asyncio.Lock()
        self._turns: dict[str, dict] = {}
        self._prefix = secrets.token_hex(2)
        self._n = 0
        self._modes: tuple | None = None

    # ------------------------------------------------------------ plumbing

    def spawn(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._task_done)
        return t

    def _task_done(self, t: asyncio.Task) -> None:
        self._tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            log.error("concierge task failed", exc_info=t.exception())

    async def drain(self) -> None:
        """Wait for every in-flight turn and utterance (tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _id(self, kind: str) -> str:
        self._n += 1
        return f"{kind}-{self._prefix}-{self._n}"

    def mac_app_present(self) -> bool:
        return self._mac_seen is not None and time.time() - self._mac_seen <= self.s.mac_app_ttl_s

    def _saw_mac_app(self) -> None:
        self._mac_seen = time.time()
        self.mac_present.set()

    # ------------------------------------------------------------ inbound

    async def handle(self, msg: object) -> None:
        if isinstance(msg, MicAudio):
            self._saw_mac_app()
            await self.stt.on_mic_audio(msg)
        elif isinstance(msg, ObjectState):
            self.world.apply_state(msg)
            await self._retarget(msg)
        elif isinstance(msg, Pickup):
            self.world.apply_pickup(msg)
            await self._on_pickup(msg)
        elif isinstance(msg, Snapshot):
            self.world.apply_snapshot(msg)
            self.ready.set()
            self.spawn(self._sync_registry())
        elif isinstance(msg, RegistryUpdate):
            self.world.set_objects(msg.objects)
            self.world.registry_version = msg.registry_version
            self.spawn(self._sync_registry())
        elif isinstance(msg, UnknownTag):
            self.world.apply_unknown_tag(msg)
        elif isinstance(msg, Transcript):
            if msg.source == "apple":
                self._saw_mac_app()
            if msg.is_final and msg.source in ("apple", "typed") and msg.text.strip():
                self.spawn(self._utterance(msg.text, msg.source))
        elif isinstance(msg, GuideFeedback):
            self._saw_mac_app()
            await self._on_feedback(msg)
        elif isinstance(msg, Playback):
            self._saw_mac_app()
            turn = self._turns.get(msg.utterance_id)
            if msg.event == "started" and turn:
                self.latency.log("playback", turn=turn["id"], utterance_id=msg.utterance_id,
                                 since_final_ms=round((msg.t - turn["t_final"]) * 1000, 1))
        elif isinstance(msg, StatusMsg):
            if msg.component == "mac_app":
                self._saw_mac_app()
                # Self-heal: the Mac app may have missed stt_mode (it connected late or restarted).
                reported = (msg.info or {}).get("stt_engine")
                if reported in ("cartesia", "apple") and reported != self.stt.engine:
                    await self.emit(SttMode(engine=self.stt.engine, reason=f"resync: {self.stt.reason}"))
        elif isinstance(msg, HeadPose):
            self._saw_mac_app()
            self.world.apply_head(msg.yaw)
        elif isinstance(msg, ListenerPose):
            self.world.apply_listener(msg.position, msg.quality)
        elif isinstance(msg, TrialStart):
            if msg.mode == "baseline":
                self.silent_trial = msg.trial_id
                await self._stop_all("cancelled")
                await self.publish_status()
        elif isinstance(msg, TrialEnd):
            if self.silent_trial is not None:
                self.silent_trial = None
                await self.publish_status()
        elif isinstance(msg, Reset):
            await self._stop_all("reset")
            self.world.unknown_tag = None
            self.silent_trial = None
            self.last_object = None
            self.router.cancel_prefetch()

    async def _sync_registry(self) -> None:
        """Rebuild the Moss index from the registry; announce if Moss became ready or failed."""
        await self.resolver.on_registry()
        await self.publish_status(only_if_changed=True)

    async def inject_typed(self, text: str) -> None:
        await self.emit(Transcript(text=text, is_final=True, source="typed"))
        self.spawn(self._utterance(text, "typed"))

    # ------------------------------------------------------------ STT callbacks

    async def on_stt_partial(self, text: str) -> None:
        await self.emit(Transcript(text=text, is_final=False, source="cartesia"))

    async def on_stt_eager(self, text: str) -> None:
        await self.emit(Transcript(text=text, is_final=False, source="cartesia"))
        if self.silent_trial is None:
            self.router.prefetch(text, self.world)

    async def on_stt_resume(self) -> None:
        self.router.cancel_prefetch()

    async def on_stt_final(self, text: str) -> None:
        await self.emit(Transcript(text=text, is_final=True, source="cartesia"))
        self.spawn(self._utterance(text, "cartesia"))

    async def on_stt_engine(self, engine: str, reason: str) -> None:
        await self.emit(SttMode(engine=engine, reason=reason))
        await self.publish_status()
        if engine == "apple" and self.s.cartesia_enabled:
            self.spawn(self.speaker.say(self._id("u"), phrase_id=policy.PHRASE_STT_FALLBACK))

    # ------------------------------------------------------------ turns

    async def _utterance(self, text: str, source: str) -> None:
        async with self._turn_lock:
            turn = {"id": self._id("t"), "t_final": time.time(), "source": source}
            self.latency.log("final_transcript", turn=turn["id"], source=source, text=text)
            if self.silent_trial is not None:
                self.latency.log("tool", turn=turn["id"], tool="silent_baseline_trial")
                return
            plan = await self._clarification(text, turn)
            if plan is None:
                t0 = time.perf_counter()
                d = await self.router.decide(text, self.world)
                self.last_decision = d
                self.latency.log("intent", turn=turn["id"], path=d.path, llm_status=d.llm_status,
                                 llm_ms=round(d.llm_ms, 1) if d.llm_ms is not None else None,
                                 vendor=d.vendor, tool=d.call.name if d.call else None,
                                 ms=round((time.perf_counter() - t0) * 1000, 1), detail=d.detail)
                plan = await self._execute(d.call, text, turn)
            await self._apply(plan, turn)
            await self.publish_status(only_if_changed=True)

    async def _clarification(self, text: str, turn: dict) -> Plan | None:
        """Resolve a follow-up against the pending candidates, or None to process normally."""
        p = self.pending
        if p is None:
            return None
        self.pending = None
        if time.time() - p.t > self.s.clarify_window_s:
            return None
        g = grammar.parse(text, {t.lower() for i in p.object_ids if i in self.world.objects
                                 for t in [self.world.objects[i].name, *self.world.objects[i].aliases]})
        query = g.args.get("query", text) if g is not None else text
        res = await self.resolver.resolve(query, candidates=p.object_ids, strict=True)
        self.latency.log("resolve", turn=turn["id"], engine=res.engine, kind=res.kind,
                         ids=res.object_ids, clarification=True)
        if res.kind == "one":
            self.latency.log("intent", turn=turn["id"], path="clarification", llm_status="skipped", tool=p.tool)
            return await self._execute(ToolCall(p.tool, {"object_id": res.object_ids[0]}), text, turn)
        if res.kind == "ambiguous":
            return policy.clarify(self.world, res.object_ids, p.tool)
        return None

    async def _target(self, call: ToolCall, turn: dict) -> RegistryObject | Plan:
        if "object_id" in call.args:
            obj = self.world.objects.get(call.args["object_id"])
            return obj if obj is not None else policy.unknown_object()
        q = call.args.get("query", "")
        if grammar.normalize(q) in PRONOUNS and self.last_object in self.world.objects:
            return self.world.objects[self.last_object]
        res = await self.resolver.resolve(q)
        self.latency.log("resolve", turn=turn["id"], engine=res.engine, kind=res.kind, ids=res.object_ids,
                         moss_status=res.moss_status,
                         moss_ms=round(res.moss_ms, 2) if res.moss_ms is not None else None)
        if res.kind == "one":
            return self.world.objects[res.object_ids[0]]
        if res.kind == "ambiguous":
            return policy.clarify(self.world, res.object_ids, call.name)
        return policy.unknown_object()

    async def _execute(self, call: ToolCall | None, text: str, turn: dict) -> Plan:
        now = time.time()
        if call is None:
            return policy.not_understood()
        if call.name == "stop_guidance":
            return policy.stop()
        if call.name == "list_objects":
            return policy.list_objects(self.world)
        if call.name == "label_object":
            fresh = self.world.fresh_unknown_tag(now, self.s.label_window_s)
            tag = call.args.get("tag") or ""
            if not tag:
                if fresh is None:
                    return policy.no_new_tag()
                tag = fresh.tag
            spot = fresh.spot if fresh is not None and fresh.tag == tag else None
            return policy.label(tag, call.args["name"], call.args.get("aliases", []), spot)
        target = await self._target(call, turn)
        if isinstance(target, Plan):
            return target
        if call.name == "chirp_fob":
            return policy.chirp(self.world, target, now, self.s.stale_s)
        if call.name == "put_in_place":
            place = call.args.get("place", "")
            area = call.args.get("area") or (self.world.resolve_area(place) if place else None)
            if area:
                return policy.put_in_place(self.world, target, area)
            if place:
                return policy.unknown_place(self.world)
            here = self.world.listener_position()
            return policy.put_here(target, here) if here else policy.ask_place(self.world, target)
        if call.name == "place_history":
            return policy.place_history(self.world, target, now)
        if call.name == "last_seen":
            advice = target.is_medication and bool(ADVICE.search(grammar.normalize(text)))
            return policy.last_seen(self.world, target, now, self.started_t, medical_question=advice)
        return policy.locate(self.world, target, now, self.s.stale_s)

    async def _apply(self, plan: Plan, turn: dict | None) -> str:
        uid = self._id("u")
        if turn is not None:
            self._turns[uid] = turn
            self.latency.log("tool", turn=turn["id"], utterance_id=uid,
                             guide=plan.guide.object_id if plan.guide else None, chirp=plan.chirp,
                             label=plan.label.name if plan.label else None, stop=plan.stop or None,
                             clarify=plan.clarify or None, phrase_id=plan.phrase_id)
        if plan.stop:
            await self._stop_all("cancelled")
        if plan.clarify:
            self.pending = Pending(plan.clarify, plan.clarify_tool or "locate_object", time.time())
        if plan.object_id:
            self.last_object = plan.object_id
            if self.guiding and plan.guide is None and plan.object_id != self.guiding.object_id:
                await self._stop_guidance("cancelled")
        if plan.guide:
            await self._start_guidance(plan.guide, uid)
        if plan.chirp:
            await self.emit(Chirp(fob_id=plan.chirp, action="start"))
            self.chirping[plan.chirp] = time.time()
        if plan.label:
            lb = plan.label
            await self.emit(Label(tag=lb.tag, name=lb.name, aliases=lb.aliases, spot=lb.spot))
        if plan.place:
            where = ({"area": plan.place.area} if plan.place.area is not None
                     else {"position": plan.place.position})
            await self.emit(PlaceItem(object_id=plan.place.object_id, t=time.time(), **where))
        if plan.text or plan.phrase_id:
            self.spawn(self.speaker.say(uid, plan.text, plan.phrase_id, turn))
        return uid

    # ------------------------------------------------------------ guidance

    async def _start_guidance(self, g: GuideTarget, uid: str) -> None:
        if self._guide_timer is not None:
            self._guide_timer.cancel()
        guiding = Guiding(g.object_id, g.name, list(g.position), uid, time.time())
        self.guiding = guiding
        await self.emit(GuideStart(object_id=g.object_id, name=g.name, target_position=list(g.position),
                                   precision=g.precision, utterance_id=uid))
        self._guide_timer = asyncio.create_task(self._guide_timeout(guiding))

    async def _guide_timeout(self, g: Guiding) -> None:
        await asyncio.sleep(self.s.guide_timeout_s)
        if self.guiding is g:
            self.guiding = None
            await self.emit(GuideStop(reason="timeout", object_id=g.object_id))
            self.spawn(self.speaker.say(self._id("u"), policy.guide_timeout(g.name)))

    async def _stop_guidance(self, reason: str) -> None:
        g, self.guiding = self.guiding, None
        if self._guide_timer is not None:
            self._guide_timer.cancel()
            self._guide_timer = None
        if g is not None:
            await self.emit(GuideStop(reason=reason, object_id=g.object_id))

    async def _stop_all(self, reason: str) -> None:
        await self._stop_guidance(reason)
        for fob in list(self.chirping):
            await self.emit(Chirp(fob_id=fob, action="stop"))
        self.chirping.clear()
        self.pending = None

    async def _retarget(self, st: ObjectState) -> None:
        """The guided object moved to a new exact position: update the ping."""
        g = self.guiding
        if g is None or st.object_id != g.object_id or st.precision != "exact" or not st.location.position:
            return
        pos = list(st.location.position)
        if pos != g.position:
            g.position = pos
            await self.emit(GuideStart(object_id=g.object_id, name=g.name, target_position=pos,
                                       precision="exact", utterance_id=g.utterance_id))

    async def _on_pickup(self, msg: Pickup) -> None:
        g = self.guiding
        if g is None or self.silent_trial is not None:
            return
        target = self.world.objects.get(g.object_id)
        if target is None:
            return
        if msg.object_id == g.object_id:
            await self._stop_guidance("found")
            await self.emit(PickupResult(expected=g.object_id, actual=msg.object_id, correct=True))
            text = policy.pickup_correct(target)
        else:
            await self.emit(PickupResult(expected=g.object_id, actual=msg.object_id, correct=False))
            text = policy.pickup_wrong(self.world, target, self.world.objects.get(msg.object_id),
                                       msg.from_spot)
        self.spawn(self.speaker.say(self._id("u"), text))

    async def _on_feedback(self, msg: GuideFeedback) -> None:
        g = self.guiding
        if (g is None or msg.object_id != g.object_id or msg.event != "behind" or msg.turn is None
                or self.silent_trial is not None):
            return
        now = time.time()
        if now - self._last_behind < self.s.behind_cooldown_s:
            return
        self._last_behind = now
        self.spawn(self.speaker.say(self._id("u"), phrase_id=f"behind_turn_{msg.turn}"))

    # ------------------------------------------------------------ status

    def status_msg(self) -> StatusMsg:
        d = self.last_decision
        intent = "claude" if self.router.chooser is not None else "grammar"
        info: dict = {
            "stt_engine": self.stt.engine,
            "stt_reason": self.stt.reason,
            "intent_engine": intent,
            "llm_model": self.s.anthropic_chat_model if self.router.chooser is not None else None,
            "last_intent_path": d.path if d else None,
            "last_llm_status": d.llm_status if d else None,
            "last_llm_ms": round(d.llm_ms, 1) if d and d.llm_ms is not None else None,
            "resolver": self.resolver.engine,
            "moss_ms": round(self.resolver.last_moss_ms, 2) if self.resolver.last_moss_ms is not None else None,
            "tts": self.speaker.mode,
            "mac_app": self.mac_app_present(),
            "guiding": self.guiding.object_id if self.guiding else None,
            "baseline_trial": self.silent_trial is not None,
        }
        detail = (f"stt={info['stt_engine']} intent={intent}"
                  f"{'/' + d.path if d else ''} resolver={info['resolver']} tts={info['tts']}")
        return StatusMsg(component="concierge", ok=True, detail=detail, info=info)

    async def publish_status(self, only_if_changed: bool = False) -> None:
        d = self.last_decision
        modes = (self.stt.engine, d.path if d else None, self.resolver.engine, self.speaker.mode,
                 self.silent_trial is not None)
        if only_if_changed and modes == self._modes:
            return
        self._modes = modes
        await self.emit(self.status_msg())

    async def on_bus_connect(self) -> None:
        await self.publish_status()
        await self.emit(SttMode(engine=self.stt.engine, reason=self.stt.reason))

    async def status_loop(self) -> None:
        while True:
            await asyncio.sleep(self.s.status_interval_s)
            await self.publish_status()
