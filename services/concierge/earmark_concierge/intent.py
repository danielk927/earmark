"""Intent: Bitdeer LLM tool choice raced against the keyword grammar.

The grammar result is computed immediately. The LLM's single tool call wins if
it arrives within the timeout and validates; otherwise the grammar result is
used. A prefetch started on Cartesia's turn.eager_end is reused when the final
transcript matches (docs/vendor-notes/cartesia.md, section 3.6).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from . import grammar
from .grammar import normalize
from .tools import DeclinedToolCall, InvalidToolCall, ToolCall, system_prompt, tool_schemas, validate_llm_call
from .world import World

log = logging.getLogger(__name__)


class ToolChooser(Protocol):
    vendor: str

    async def choose(self, text: str, world: World) -> list[tuple[str, str]]:
        """Return the model's tool calls as (name, arguments_json)."""


class BitdeerChooser:
    """OpenAI-compatible chat completions on Bitdeer (docs/vendor-notes/bitdeer.md, 3.1)."""

    vendor = "bitdeer"

    def __init__(self, api_key: str, base_url: str, model: str, timeout_s: float) -> None:
        from openai import AsyncOpenAI

        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0)

    async def choose(self, text: str, world: World) -> list[tuple[str, str]]:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt(world)},
                {"role": "user", "content": text},
            ],
            tools=tool_schemas(world),
            tool_choice="required",
            parallel_tool_calls=False,
            max_tokens=200,
            temperature=0,
            extra_body={"reasoning_effort": "none"},
        )
        calls = resp.choices[0].message.tool_calls or []
        return [(c.function.name, c.function.arguments) for c in calls]

    async def close(self) -> None:
        await self.client.close()


@dataclass
class Decision:
    call: ToolCall | None
    path: str  # llm | grammar
    llm_status: str  # ok | disabled | timeout | invalid | declined | error
    llm_ms: float | None = None
    vendor: str | None = None
    detail: str | None = None


class IntentRouter:
    def __init__(self, chooser: ToolChooser | None, timeout_s: float) -> None:
        self.chooser = chooser
        self.timeout_s = timeout_s
        self._prefetch: tuple[str, float, asyncio.Task] | None = None

    def prefetch(self, text: str, world: World) -> None:
        if self.chooser is None or not text.strip():
            return
        key = normalize(text)
        if self._prefetch and self._prefetch[0] == key:
            return
        self.cancel_prefetch()
        self._prefetch = (key, time.perf_counter(), asyncio.create_task(self.chooser.choose(text, world)))

    def cancel_prefetch(self) -> None:
        if self._prefetch:
            self._prefetch[2].cancel()
            self._prefetch = None

    async def decide(self, text: str, world: World) -> Decision:
        terms = {t.lower() for o in world.objects.values() for t in [o.name, *o.aliases]}
        g = grammar.parse(text, terms)
        if self.chooser is None:
            return Decision(g, "grammar", "disabled")

        key = normalize(text)
        if self._prefetch and self._prefetch[0] == key:
            _, t0, task = self._prefetch
        else:
            self.cancel_prefetch()
            t0, task = time.perf_counter(), asyncio.create_task(self.chooser.choose(text, world))
        self._prefetch = None
        remaining = max(0.05, self.timeout_s - (time.perf_counter() - t0))
        vendor = self.chooser.vendor
        try:
            calls = await asyncio.wait_for(task, remaining)
        except asyncio.TimeoutError:
            return Decision(g, "grammar", "timeout", (time.perf_counter() - t0) * 1000, vendor)
        except Exception as e:
            log.info("llm error (%s); using grammar", type(e).__name__)
            return Decision(g, "grammar", "error", (time.perf_counter() - t0) * 1000, vendor,
                            type(e).__name__)
        ms = (time.perf_counter() - t0) * 1000
        if len(calls) != 1:
            return Decision(g, "grammar", "invalid", ms, vendor, f"{len(calls)} tool calls")
        try:
            call = validate_llm_call(calls[0][0], calls[0][1], world)
        except DeclinedToolCall as e:
            return Decision(g, "grammar", "declined", ms, vendor, str(e))
        except InvalidToolCall as e:
            log.info("llm tool call rejected: %s", e)
            return Decision(g, "grammar", "invalid", ms, vendor, str(e))
        return Decision(call, "llm", "ok", ms, vendor)
