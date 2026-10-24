"""Bitdeer-hosted chat model and the multi-step tool-calling loop.

The model only chooses tools and phrases the answer; every fact it sees was fetched and
formatted by code (tools.py). Any failure raises `LlmError` and the pipeline falls back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

import httpx
import openai
from openai import AsyncOpenAI

from .config import LLM_MAX_TOKENS, LLM_REASONING_EFFORT, LLM_REQUEST_TIMEOUT_S, LLM_TOTAL_BUDGET_S, MAX_TOOL_CALLS
from .household import HouseholdClock
from .tools import TOOL_SPECS, Toolbox

log = logging.getLogger("earmark.memory.llm")

SYSTEM_PROMPT = """You are Earmark Memory. You answer caregivers' questions about a blind or low-vision person's home, using Earmark's records. Earmark tracks household objects with NFC spots inside containers (a cupboard, a drawer, a bag, a box) and logs when objects are picked up or put down. Name the container when you say where something is.

The household has one primary person. Caregivers may call them Mom, Dad, or by name; all of these mean the household's primary person.

Rules:
1. Look up the data with the tools before answering, and answer only from tool results. Never guess or invent. If the records don't cover the question, say so plainly.
2. Quote times and days exactly as the tools give them (they are already in the household's time zone).
3. No medical advice, ever. Don't suggest doses, timing, or what to do about a missed dose, and don't interpret health. Report only what the records show. If asked what to do, say you can't advise and suggest contacting their clinician or pharmacist.
4. "Taken" means the medication bottle was picked up during that dose's window; Earmark cannot see whether pills were swallowed.
5. "Evening" or "tonight" means doses scheduled from 5 PM on; "morning" means doses before noon. If today's dose isn't due yet, also report the most recent earlier day.
6. Use at most 4 tool calls. Reply in 1 to 3 plain sentences, no Markdown."""


class LlmError(Exception):
    """The LLM path failed; the message is a short reason for the logs."""


@dataclass
class ToolRequest:
    id: str
    name: str
    arguments: str


@dataclass
class AssistantTurn:
    content: str | None
    tool_calls: list[ToolRequest] = field(default_factory=list)

    def as_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in self.tool_calls
            ]
        return msg


class ChatModel(Protocol):
    model: str

    async def complete(self, messages: list[dict[str, Any]], *, allow_tools: bool) -> AssistantTurn: ...


class BitdeerChatModel:
    """OpenAI-compatible client for Bitdeer: bounded timeout, no SDK retries, reasoning off."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_s: float = LLM_REQUEST_TIMEOUT_S,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0, http_client=http_client)

    async def complete(self, messages: list[dict[str, Any]], *, allow_tools: bool) -> AssistantTurn:
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOL_SPECS,
                tool_choice="auto" if allow_tools else "none",
                max_tokens=LLM_MAX_TOKENS,
                temperature=0.2,
                extra_body={"reasoning_effort": LLM_REASONING_EFFORT},
            )
        except openai.APITimeoutError as exc:
            raise LlmError("Bitdeer request timed out") from exc
        except openai.APIStatusError as exc:
            raise LlmError(f"Bitdeer returned HTTP {exc.status_code}") from exc
        except openai.APIError as exc:
            raise LlmError(f"Bitdeer request failed ({type(exc).__name__})") from exc
        if not resp.choices:
            raise LlmError("Bitdeer returned no choices")
        msg = resp.choices[0].message
        calls = [
            ToolRequest(c.id, c.function.name, c.function.arguments or "{}")
            for c in (msg.tool_calls or [])
            if getattr(c, "function", None) is not None
        ]
        return AssistantTurn(content=msg.content, tool_calls=calls)


@dataclass
class LlmResult:
    text: str
    rounds: int
    tool_calls: int


def household_context(clock: HouseholdClock) -> str:
    yesterday = clock.today - timedelta(days=1)
    return (
        f"Household time now: {clock.now_phrase()} ({clock.timezone}). "
        f"Today is {clock.today.isoformat()}; yesterday was {yesterday.isoformat()}."
    )


async def run_tool_loop(
    model: ChatModel,
    toolbox: Toolbox,
    question: str,
    *,
    max_tool_calls: int = MAX_TOOL_CALLS,
    budget_s: float = LLM_TOTAL_BUDGET_S,
) -> LlmResult:
    try:
        async with asyncio.timeout(budget_s):
            return await _loop(model, toolbox, question, max_tool_calls)
    except TimeoutError as exc:
        raise LlmError(f"LLM path exceeded its {budget_s:g} s budget") from exc


async def _loop(model: ChatModel, toolbox: Toolbox, question: str, max_tool_calls: int) -> LlmResult:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},  # byte-identical across calls (prefix caching)
        {"role": "system", "content": household_context(toolbox.clock)},
        {"role": "user", "content": question},
    ]
    calls_made = 0
    for round_no in range(1, max_tool_calls + 2):
        allow_tools = calls_made < max_tool_calls
        started = time.perf_counter()
        turn = await model.complete(messages, allow_tools=allow_tools)
        ms = (time.perf_counter() - started) * 1000
        log.info(
            "llm round %d model=%s %.0f ms -> %s",
            round_no,
            model.model,
            ms,
            ", ".join(f"{c.name}({c.arguments})" for c in turn.tool_calls) or "final answer",
        )
        if not turn.tool_calls:
            text = (turn.content or "").strip()
            if not text:
                raise LlmError("empty answer")
            return LlmResult(text, round_no, calls_made)
        if not allow_tools:
            raise LlmError("model kept calling tools after the limit")
        messages.append(turn.as_message())
        for call in turn.tool_calls:
            if calls_made >= max_tool_calls:
                result: dict[str, Any] = {"ok": False, "error": "tool call limit reached; answer with the data you have"}
            else:
                calls_made += 1
                result = await toolbox.call_json(call.name, call.arguments)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
    raise LlmError("no final answer")
