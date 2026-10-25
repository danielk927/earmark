"""Wire the concierge together and run it against the bus."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .bus import BusClient
from .config import Settings
from .core import Concierge
from .intent import AnthropicChooser, IntentRouter
from .latency import LatencyLog
from .moss_index import MossIndex
from .resolver import Resolver
from .speech import Speaker, load_phrases
from .stt import CartesiaStt
from .tts import SonicTts
from .world import World, household_timezone

log = logging.getLogger(__name__)
TEXT_WAIT_FOR_MAC_APP_S = 6.0


def build(settings: Settings, emit, bus_connected=lambda: True) -> Concierge:
    world = World(settings.timezone or household_timezone(settings.registry_paths), pinned=bool(settings.timezone))
    latency = LatencyLog(settings.latency_log)
    index = (MossIndex(settings.moss_project_id, settings.moss_project_key, settings.moss_index_name)
             if settings.moss_enabled else None)
    resolver = Resolver(world, index, settings.moss_min_score, settings.moss_margin)
    chooser = (AnthropicChooser(settings.anthropic_api_key, settings.anthropic_chat_model, settings.llm_timeout_s)
               if settings.anthropic_enabled else None)
    router = IntentRouter(chooser, settings.llm_timeout_s)
    tts = SonicTts(settings) if settings.tts_enabled else None
    stt = CartesiaStt(settings, keyterms=lambda: ["Earmark"] + [
        t for o in world.objects.values() for t in [o.name, *o.aliases]])
    holder: dict = {}
    speaker = Speaker(
        load_phrases(settings.phrases_path), tts, emit,
        mac_app_present=lambda: bus_connected() and holder["core"].mac_app_present(),
        latency=latency, first_chunk_timeout_s=settings.tts_first_chunk_timeout_s,
        encoding=settings.tts_encoding, sample_rate=settings.tts_sample_rate, say_cmd=settings.say_cmd,
    )
    core = Concierge(settings, world, resolver, router, speaker, stt, latency, emit)
    holder["core"] = core
    return core


def describe(settings: Settings) -> str:
    return (f"bus={settings.bus_url} stt={'cartesia' if settings.cartesia_enabled else 'apple (no key)'} "
            f"tts={'cartesia' if settings.tts_enabled else 'system voice (no key/voice)'} "
            f"llm={'claude ' + settings.anthropic_chat_model if settings.anthropic_enabled else 'off (grammar)'} "
            f"resolver={'moss' if settings.moss_enabled else 'fallback (no key)'}")


async def run(settings: Settings, text: str | None = None, repl: bool = False) -> None:
    bus: BusClient | None = None

    async def emit(msg) -> None:
        await bus.send(msg)

    core_box: dict = {}

    async def on_message(msg) -> None:
        await core_box["core"].handle(msg)

    async def on_connect() -> None:
        await core_box["core"].on_bus_connect()

    bus = BusClient(settings.bus_url, on_message, on_connect)
    core = build(settings, emit, bus_connected=lambda: bus.connected)
    core_box["core"] = core
    log.info("concierge starting: %s", describe(settings))
    if core.speaker.tts is not None:
        core.speaker.tts.warm()

    main = asyncio.current_task()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, main.cancel)  # clean shutdown
    tasks = [asyncio.create_task(bus.run_forever()), asyncio.create_task(core.status_loop())]
    if text:
        tasks.append(asyncio.create_task(_inject_once(core, text)))
    if repl:
        tasks.append(asyncio.create_task(_repl(core)))
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        await core.stt.close()
        if core.speaker.tts is not None:
            await core.speaker.tts.close()
        if core.resolver.index is not None:
            await core.resolver.index.close()


async def _inject_once(core: Concierge, text: str) -> None:
    await core.ready.wait()
    try:  # give the Mac app's periodic status a chance to arrive, so speech goes to it
        await asyncio.wait_for(core.mac_present.wait(), TEXT_WAIT_FOR_MAC_APP_S)
    except asyncio.TimeoutError:
        log.info("no Mac app seen on the bus; speech will use local `say`")
    log.info("injecting typed transcript: %s", text)
    await core.inject_typed(text)


async def _repl(core: Concierge) -> None:
    await core.ready.wait()
    print("Type a request (Ctrl-C to quit).", file=sys.stderr)
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if line == "":
            return  # EOF: stop reading, keep running
        if line.strip():
            await core.inject_typed(line.strip())
