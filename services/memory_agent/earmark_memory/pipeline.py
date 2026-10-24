"""One question in, one grounded answer out. Shared by the CLI and the uAgent.

Paths, in order:
  guard    - dosing or health questions are answered by code only (facts, never advice).
  llm      - Bitdeer tool-calling loop, accepted only if it used a tool for a data question
             and its text passes the no-medical-advice check.
  fallback - the deterministic keyword router, whenever the LLM is off, slow, or rejected.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Literal

from .config import MAX_QUESTION_CHARS, ConfigError, Settings
from .convex import ConvexError, ConvexReader, HttpConvexReader
from .describe import SpaceLabels
from .fixture import FixtureConvexReader
from .llm import BitdeerChatModel, ChatModel, LlmError, run_tool_loop
from .router import HELP_TEXT, analyze, unreachable_text
from .router import answer as route_answer
from .tools import ToolCallRecord, Toolbox

log = logging.getLogger("earmark.memory")

Path = Literal["llm", "fallback", "guard"]

# Phrases that would make an LLM answer medical advice; such answers are replaced by the code-built one.
_ADVICE_OUT = [
    r"\b(you|she|he|they|mom|dad|mum)\s+(should|could|can|may|must|might want to|needs? to)\s+(take|give|skip|double|increase|decrease|stop|wait|resume)\b",
    r"\b(double|extra|additional|make[- ]up)\s+(a\s+|the\s+|her\s+|his\s+|their\s+)?dose\b",
    r"\b(take|give)\s+(it|them|the (pills?|dose|medication))\s+now\b",
    r"\b\d+(\.\d+)?\s?(mg|milligrams?)\b",
    r"\b(safe|unsafe|dangerous|harmful)\s+to\s+(take|skip|double|miss)\b",
    r"\b(blood pressure|bp)\s+(is|was|seems|looks)\s+(fine|ok|okay|normal|high|low|under control|good)\b",
    r"\b(not|nothing) to worry about\b",
]


def looks_like_medical_advice(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in _ADVICE_OUT)


@dataclass
class Answer:
    text: str
    path: Path
    model: str | None = None
    reason: str | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    ms: float = 0.0


class MemoryPipeline:
    def __init__(self, reader: ConvexReader, chat_model: ChatModel | None = None, labels: SpaceLabels | None = None):
        self.reader = reader
        self.chat_model = chat_model
        self.labels = labels if labels is not None else SpaceLabels.load()

    async def aclose(self) -> None:
        await self.reader.aclose()

    async def answer(self, question: str) -> Answer:
        started = time.perf_counter()
        result = await self._answer(question.strip()[:MAX_QUESTION_CHARS])
        result.ms = (time.perf_counter() - started) * 1000
        log.info("answered path=%s model=%s reason=%s tools=[%s] total=%.0f ms",
                 result.path, result.model or "-", result.reason or "-",
                 "; ".join(r.short() for r in result.tool_calls), result.ms)
        return result

    async def _answer(self, question: str) -> Answer:
        log.info("question: %r (data: %s, llm: %s)", question, self.reader.source,
                 self.chat_model.model if self.chat_model else "off")
        analysis = analyze(question)
        if not question:
            return Answer(HELP_TEXT, "fallback", reason="empty question")
        try:
            clock = await self.reader.clock()
        except ConvexError as exc:
            return Answer(unreachable_text(exc), "fallback", reason=f"clock: {exc.kind}")

        if analysis.medical:
            tb = Toolbox(self.reader, clock, self.labels)
            text = await route_answer(question, tb, analysis)
            return Answer(text, "guard", reason="medical question: facts only, answered by code", tool_calls=tb.records)

        reason = "LLM disabled (no BITDEER_API_KEY)"
        if self.chat_model is not None:
            tb = Toolbox(self.reader, clock, self.labels)
            try:
                result = await run_tool_loop(self.chat_model, tb, question)
            except LlmError as exc:
                reason = f"LLM failed: {exc}"
            else:
                if analysis.needs_data and result.tool_calls == 0:
                    reason = "LLM answered without looking up any data"
                elif looks_like_medical_advice(result.text):
                    reason = "LLM answer failed the no-medical-advice check"
                    log.warning("rejected LLM answer: %r", result.text)
                    fb = Toolbox(self.reader, clock, self.labels)
                    text = await route_answer(question, fb, analysis)
                    return Answer(text, "guard", self.chat_model.model, reason, tb.records + fb.records)
                else:
                    return Answer(result.text, "llm", self.chat_model.model, f"{result.rounds} rounds", tb.records)
            log.info("falling back to the keyword router: %s", reason)

        fb = Toolbox(self.reader, clock, self.labels)
        text = await route_answer(question, fb, analysis)
        return Answer(text, "fallback", reason=reason, tool_calls=fb.records)


def build_pipeline(settings: Settings, *, fixture: bool = False, use_llm: bool = True) -> MemoryPipeline:
    """Real services when configured; the offline fixture and the keyword router otherwise."""
    if fixture or not settings.convex_configured:
        if not fixture:
            log.warning("CONVEX_SITE_URL is not set: answering from the offline fixture (seed data, fixed clock)")
        reader: ConvexReader = FixtureConvexReader()
    else:
        if not settings.read_secret:
            raise ConfigError("CONVEX_SITE_URL is set but EARMARK_READ_SECRET is not; set both (see services/memory_agent/README.md)")
        reader = HttpConvexReader(settings.convex_site_url, settings.read_secret)

    chat_model: ChatModel | None = None
    if use_llm and settings.llm_enabled:
        chat_model = BitdeerChatModel(api_key=settings.bitdeer_api_key, base_url=settings.bitdeer_base_url,
                                      model=settings.bitdeer_model)
    elif use_llm:
        log.warning("BITDEER_API_KEY is not set: answering with the deterministic keyword router")
    return MemoryPipeline(reader, chat_model)
