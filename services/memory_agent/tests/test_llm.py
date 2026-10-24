"""The Bitdeer tool loop: request shape, multi-step tool use, limits, timeouts, and guards."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from earmark_memory.describe import SpaceLabels
from earmark_memory.fixture import FixtureConvexReader
from earmark_memory.llm import AssistantTurn, BitdeerChatModel, LlmError, ToolRequest
from earmark_memory.pipeline import MemoryPipeline, looks_like_medical_advice


class ScriptedModel:
    """A fake ChatModel that plays back turns and records what it was sent."""

    model = "scripted"

    def __init__(self, turns, delay_s: float = 0.0):
        self.turns = list(turns)
        self.delay_s = delay_s
        self.calls: list[tuple[list[dict], bool]] = []

    async def complete(self, messages, *, allow_tools):
        self.calls.append(([dict(m) for m in messages], allow_tools))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        turn = self.turns.pop(0) if self.turns else AssistantTurn(None, [ToolRequest("x", "list_objects", "{}")])
        if isinstance(turn, Exception):
            raise turn
        return turn


def call(name: str, args: dict, id_: str = "c1") -> AssistantTurn:
    return AssistantTurn(None, [ToolRequest(id_, name, json.dumps(args))])


def pipeline_with(model) -> MemoryPipeline:
    return MemoryPipeline(FixtureConvexReader(), model, SpaceLabels.load())


async def test_multi_step_tool_use_and_grounded_answer():
    model = ScriptedModel(
        [
            call("adherence", {"date": "today"}, "c1"),
            call("adherence", {"date": "yesterday"}, "c2"),
            AssistantTurn("Not yet tonight; yesterday's 8:00 PM dose was missed."),
        ]
    )
    a = await pipeline_with(model).answer("Did Mom take her evening pills?")
    assert (a.path, a.model) == ("llm", "scripted")
    assert a.text == "Not yet tonight; yesterday's 8:00 PM dose was missed."
    assert [r.args["date"] for r in a.tool_calls] == ["today", "2025-10-23"]
    final_messages = model.calls[-1][0]
    assert final_messages[1]["content"].startswith("Household time now: 5:00 PM on Friday, October 24")
    tool_msgs = [m for m in final_messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2"]
    yesterday = json.loads(tool_msgs[1]["content"])
    assert (
        yesterday["doses"][1]["summary"]
        == "The 8:00 PM dose of blood pressure pills was missed (no pickup of the bottle was recorded for it)."
    )
    assistant = [m for m in final_messages if m["role"] == "assistant"]
    assert assistant[0]["tool_calls"][0]["function"]["name"] == "adherence"


async def test_tool_calls_are_capped_at_four_then_tools_are_disabled():
    model = ScriptedModel([call("list_objects", {}, f"c{i}") for i in range(4)] + [AssistantTurn("Pepper hasn't been touched.")])
    a = await pipeline_with(model).answer("What hasn't been touched in a week?")
    assert a.path == "llm"
    assert len(a.tool_calls) == 4
    assert [allow for _, allow in model.calls] == [True, True, True, True, False]


async def test_parallel_calls_beyond_the_cap_are_refused():
    many = AssistantTurn(None, [ToolRequest(f"c{i}", "list_objects", "{}") for i in range(6)])
    model = ScriptedModel([many, AssistantTurn("Pepper.")])
    a = await pipeline_with(model).answer("What hasn't been touched in a week?")
    assert len(a.tool_calls) == 4
    refused = [json.loads(m["content"]) for m in model.calls[-1][0] if m["role"] == "tool"][4:]
    assert all(r["ok"] is False and "limit" in r["error"] for r in refused)


async def test_model_that_never_stops_calling_tools_falls_back():
    a = await pipeline_with(ScriptedModel([])).answer("What hasn't been touched in a week?")
    assert a.path == "fallback" and "kept calling tools" in a.reason
    assert a.text.startswith("Not picked up or put down in the last week: the pepper")


async def test_slow_model_hits_the_budget_and_falls_back(monkeypatch):
    from earmark_memory import llm

    async def bounded(model, toolbox, question):
        return await llm.run_tool_loop(model, toolbox, question, budget_s=0.2)

    monkeypatch.setattr("earmark_memory.pipeline.run_tool_loop", bounded)
    p = pipeline_with(ScriptedModel([AssistantTurn("late answer")], delay_s=1.0))
    loop = asyncio.get_running_loop()
    started = loop.time()
    a = await p.answer("Where did Dad leave his keys?")
    assert loop.time() - started < 0.9
    assert a.path == "fallback" and "budget" in a.reason
    assert "in the drawer" in a.text


async def test_llm_error_falls_back():
    a = await pipeline_with(ScriptedModel([LlmError("Bitdeer returned HTTP 503")])).answer("Where did Dad leave his keys?")
    assert a.path == "fallback" and "HTTP 503" in a.reason
    assert "in the drawer" in a.text


async def test_answer_without_any_lookup_is_rejected():
    a = await pipeline_with(ScriptedModel([AssistantTurn("Your keys are in the car.")])).answer("Where did Dad leave his keys?")
    assert a.path == "fallback" and "without looking up" in a.reason
    assert "car" not in a.text


async def test_greeting_may_be_answered_without_tools():
    a = await pipeline_with(ScriptedModel([AssistantTurn("Hi! Ask me where things are.")])).answer("hello")
    assert a.path == "llm"


async def test_advice_in_an_llm_answer_is_replaced_by_facts():
    model = ScriptedModel(
        [call("adherence", {"date": "yesterday"}), AssistantTurn("She missed it, so she should take two pills tonight.")]
    )
    a = await pipeline_with(model).answer("Did Mom take her evening pills yesterday?")
    assert a.path == "guard" and "no-medical-advice" in a.reason
    assert "two pills" not in a.text
    assert "the 8:00 PM dose of blood pressure pills was missed" in a.text


async def test_medical_questions_never_reach_the_llm():
    model = ScriptedModel([AssistantTurn("Yes, double it.")])
    a = await pipeline_with(model).answer("Should she take a double dose tonight?")
    assert a.path == "guard" and model.calls == []


@pytest.mark.parametrize(
    "text,flag",
    [
        ("She should take her pills now.", True),
        ("You could give a double dose.", True),
        ("Take 10 mg in the morning.", True),
        ("It's safe to skip one.", True),
        ("Her blood pressure is fine.", True),
        ("Yesterday's 8:00 PM dose was missed; no pickup was recorded.", False),
        ("I can't advise on that; please check with her clinician or pharmacist.", False),
    ],
)
def test_advice_detector(text, flag):
    assert looks_like_medical_advice(text) is flag


# ---------------------------------------------------------------- the real OpenAI-compatible client


def _completion(message: dict) -> dict:
    return {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


async def test_bitdeer_request_shape_and_tool_call_parsing():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json=_completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "t1", "type": "function", "function": {"name": "find_object", "arguments": '{"name": "keys"}'}}
                    ],
                }
            ),
        )

    model = BitdeerChatModel(
        api_key="sk-test",
        base_url="https://api-inference.bitdeer.ai/v1",
        model="deepseek-ai/DeepSeek-V4.1-Flash-1017",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    turn = await model.complete([{"role": "user", "content": "Where are the keys?"}], allow_tools=True)
    assert turn.tool_calls[0].name == "find_object" and json.loads(turn.tool_calls[0].arguments) == {"name": "keys"}
    req = seen[0]
    assert str(req.url) == "https://api-inference.bitdeer.ai/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-test"
    body = json.loads(req.content)
    assert body["model"] == "deepseek-ai/DeepSeek-V4.1-Flash-1017"
    assert body["reasoning_effort"] == "none"
    assert body["tool_choice"] == "auto" and {t["function"]["name"] for t in body["tools"]} == {
        "find_object",
        "list_objects",
        "history",
        "adherence",
        "daily_summary",
    }
    assert body["max_tokens"] == 500


async def test_bitdeer_errors_are_not_retried_and_become_llm_errors():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(503, json={"error": {"message": "busy", "type": "x", "param": None, "code": "SERVICE_UNAVAILABLE"}})

    model = BitdeerChatModel(
        api_key="sk-test",
        base_url="https://api-inference.bitdeer.ai/v1",
        model="m",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LlmError, match="HTTP 503"):
        await model.complete([{"role": "user", "content": "hi"}], allow_tools=False)
    assert len(seen) == 1  # max_retries=0


async def test_bitdeer_timeout_becomes_llm_error():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    model = BitdeerChatModel(
        api_key="sk-test",
        base_url="https://api-inference.bitdeer.ai/v1",
        model="m",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LlmError, match="timed out"):
        await model.complete([{"role": "user", "content": "hi"}], allow_tools=False)
