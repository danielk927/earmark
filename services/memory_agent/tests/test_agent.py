"""Chat Protocol: the handler with a fake context, agent construction, and a real two-agent exchange."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from earmark_memory.agent import APOLOGY, build_agent, handle_chat_message
from earmark_memory.config import ConfigError, load_settings

SERVICE_DIR = Path(__file__).resolve().parents[1]


class FakeContext:
    def __init__(self):
        self.sent: list[tuple[str, object]] = []
        self.logger = logging.getLogger("test.ctx")
        self.session = uuid4()

    async def send(self, destination, message):
        self.sent.append((destination, message))


async def _answer(question: str) -> str:
    return f"answer to: {question}"


async def test_acknowledges_then_replies_with_text():
    ctx, msg = FakeContext(), ChatMessage(content=[TextContent(text="Did Mom take her evening pills?")])
    await handle_chat_message(ctx, "agent1qsender", msg, _answer)
    (dest1, ack), (dest2, reply) = ctx.sent
    assert dest1 == dest2 == "agent1qsender"
    assert isinstance(ack, ChatAcknowledgement) and ack.acknowledged_msg_id == msg.msg_id
    assert isinstance(reply, ChatMessage)
    assert reply.text() == "answer to: Did Mom take her evening pills?"
    assert isinstance(reply.content[0], TextContent) and isinstance(reply.content[-1], EndSessionContent)


async def test_real_pipeline_answer_in_the_reply(pipeline):
    ctx = FakeContext()
    msg = ChatMessage(content=[StartSessionContent(), TextContent(text="Did Mom take her evening pills?")])

    async def answer(q):
        return (await pipeline.answer(q)).text

    await handle_chat_message(ctx, "agent1qsender", msg, answer)
    assert isinstance(ctx.sent[0][1], ChatAcknowledgement)
    assert "the 8:00 PM dose of blood pressure pills was missed" in ctx.sent[1][1].text()


async def test_start_session_only_and_end_session_are_acknowledged_without_reply():
    for content in ([StartSessionContent()], [EndSessionContent()], [TextContent(text="bye"), EndSessionContent()]):
        ctx, msg = FakeContext(), ChatMessage(content=content)
        await handle_chat_message(ctx, "agent1qsender", msg, _answer)
        assert len(ctx.sent) == 1 and isinstance(ctx.sent[0][1], ChatAcknowledgement)


async def test_a_failing_answer_still_gets_a_reply():
    async def boom(q):
        raise RuntimeError("nope")

    ctx = FakeContext()
    await handle_chat_message(ctx, "agent1qsender", ChatMessage(content=[TextContent(text="hi")]), boom)
    assert ctx.sent[1][1].text() == APOLOGY


@pytest.fixture
def loop():
    """uAgents' Agent() binds the thread's current event loop, so sync tests need one."""
    new = asyncio.new_event_loop()
    asyncio.set_event_loop(new)
    yield new
    pending = asyncio.all_tasks(new)  # e.g. the manifest publish that include() schedules; never run it here
    for task in pending:
        task.cancel()
    new.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    asyncio.set_event_loop(None)
    new.close()


def test_mailbox_requires_a_seed(pipeline, loop):
    with pytest.raises(ConfigError, match="MEMORY_AGENT_SEED"):
        build_agent(load_settings({}), pipeline, mailbox=True)


def test_agent_speaks_the_chat_protocol(pipeline, tmp_path, monkeypatch, loop):
    monkeypatch.chdir(tmp_path)  # anything uAgents writes to the cwd lands here
    seeded = build_agent(
        load_settings({"MEMORY_AGENT_SEED": "test seed phrase for earmark memory unit tests"}), pipeline, mailbox=False
    )
    assert seeded.name == "earmark-memory"
    assert seeded.address.startswith("agent1q")
    assert (
        seeded.address
        == build_agent(
            load_settings({"MEMORY_AGENT_SEED": "test seed phrase for earmark memory unit tests"}), pipeline, mailbox=False
        ).address
    )
    assert chat_protocol_spec.digest in seeded.protocols
    local = build_agent(load_settings({}), pipeline, mailbox=False)
    assert local.address != seeded.address
    assert list(tmp_path.iterdir()) == []  # no private_keys.json for the throwaway identity


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_two_agent_chat_exchange_end_to_end():
    question = "Did Mom take her evening pills?"
    proc = subprocess.run(
        [sys.executable, "-m", "tests.chat_e2e", str(_free_port()), str(_free_port()), question],
        cwd=SERVICE_DIR,
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), **{k: v for k, v in os.environ.items() if k == "PYTHONPATH"}},
    )
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("E2E_RESULT ")), None)
    assert line, proc.stdout[-2000:] + proc.stderr[-4000:]
    result = json.loads(line.removeprefix("E2E_RESULT "))
    assert result["acks"] == [{"from_memory": True, "id": result["sent_id"]}]
    (reply,) = result["replies"]
    assert reply["from_memory"] and reply["ends_session"]
    assert "Yesterday (Thursday, October 23): the 8:00 PM dose of blood pressure pills was missed" in reply["text"]
