"""Two real uAgents in one process: a client sends a ChatMessage, the memory agent answers.

Run by test_agent.py in a subprocess (uAgents owns the event loop). Offline: both agents resolve
each other with RulesBasedResolver and Almanac registration is disabled. Prints one JSON line.
Usage: python -m tests.chat_e2e <memory_port> <client_port> <question>
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys

from uagents import Agent, Context, Protocol
from uagents.resolver import RulesBasedResolver
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from earmark_memory.agent import build_agent
from earmark_memory.config import load_settings
from earmark_memory.pipeline import build_pipeline


class NoRegistration:
    async def register(self, *args, **kwargs) -> None:
        return None


def main() -> None:
    memory_port, client_port, question = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    rules: dict[str, str] = {}
    settings = load_settings({"MEMORY_AGENT_PORT": str(memory_port)})
    memory = build_agent(
        settings,
        build_pipeline(settings, fixture=True, use_llm=False),
        mailbox=False,
        endpoint=[f"http://127.0.0.1:{memory_port}/submit"],
        resolve=RulesBasedResolver(rules),
    )
    client = Agent(
        name="e2e-client",
        seed=secrets.token_urlsafe(32),
        port=client_port,
        endpoint=[f"http://127.0.0.1:{client_port}/submit"],
        resolve=RulesBasedResolver(rules),
        enable_agent_inspector=False,
    )
    rules[memory.address] = f"http://127.0.0.1:{memory_port}/submit"
    rules[client.address] = f"http://127.0.0.1:{client_port}/submit"
    for a in (memory, client):
        a.update_registration_policy(NoRegistration())

    result: dict = {"acks": [], "replies": []}
    done = asyncio.Event()
    proto = Protocol(spec=chat_protocol_spec)

    @proto.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        result["acks"].append({"from_memory": sender == memory.address, "id": str(msg.acknowledged_msg_id)})

    @proto.on_message(ChatMessage)
    async def on_reply(ctx: Context, sender: str, msg: ChatMessage) -> None:
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        result["replies"].append(
            {
                "from_memory": sender == memory.address,
                "text": msg.text(),
                "ends_session": any(isinstance(c, EndSessionContent) for c in msg.content),
            }
        )
        done.set()

    client.include(proto)

    @client.on_event("startup")
    async def ask(ctx: Context) -> None:
        msg = ChatMessage(content=[StartSessionContent(), TextContent(text=question)])
        result["sent_id"] = str(msg.msg_id)
        await ctx.send(memory.address, msg)

    loop = memory._loop
    for a in (memory, client):
        loop.create_task(a.run_async())

    async def wait() -> None:
        await asyncio.wait_for(done.wait(), timeout=30)
        await asyncio.sleep(0.5)  # let the client's ack reach the memory agent

    loop.run_until_complete(wait())
    print("E2E_RESULT " + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
