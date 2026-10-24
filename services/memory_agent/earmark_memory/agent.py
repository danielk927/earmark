"""The Fetch.ai uAgent: Agent Chat Protocol over an Agentverse mailbox (docs/vendor-notes/fetchai.md)."""
from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from uagents import Agent, Context, Protocol
from uagents.resolver import Resolver
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from .config import AGENTVERSE_README, SEED_HELP, ConfigError, Settings
from .pipeline import MemoryPipeline

log = logging.getLogger("earmark.memory.agent")

DESCRIPTION = (
    "Answers caregivers' questions about a blind or low-vision person's home from Earmark's records: "
    "where objects are, medication bottle pickups, and what hasn't been touched. Facts only, no medical advice."
)
APOLOGY = "Sorry, I couldn't answer that just now. Please try again in a minute."

AnswerFn = Callable[[str], Awaitable[str]]


async def handle_chat_message(ctx: Any, sender: str, msg: ChatMessage, answer: AnswerFn) -> None:
    """Acknowledge every message, then reply with one text answer (and end the session, as the ASI:One example does)."""
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    who = sender[:16] + "..."
    if any(isinstance(c, StartSessionContent) for c in msg.content):
        ctx.logger.info(f"session started by {who}")
    if any(isinstance(c, EndSessionContent) for c in msg.content):
        ctx.logger.info(f"session ended by {who}")
        return
    question = msg.text().strip()
    if not question:
        return  # e.g. a start-session-only message
    try:
        reply = await answer(question)
    except Exception:  # never leave a chat without a reply
        ctx.logger.exception("answer failed")
        reply = APOLOGY
    await ctx.send(sender, ChatMessage(content=[TextContent(text=reply), EndSessionContent()]))


def build_chat_protocol(answer: AnswerFn) -> Protocol:
    proto = Protocol(spec=chat_protocol_spec)

    @proto.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
        await handle_chat_message(ctx, sender, msg, answer)

    @proto.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        ctx.logger.debug(f"ack from {sender[:16]}... for {msg.acknowledged_msg_id}")

    return proto


def build_agent(
    settings: Settings,
    pipeline: MemoryPipeline,
    *,
    mailbox: bool,
    endpoint: list[str] | None = None,
    resolve: Resolver | None = None,
) -> Agent:
    """The memory agent. Mailbox mode requires MEMORY_AGENT_SEED (ConfigError otherwise).

    Without a seed (local-only mode) the identity is a throwaway kept in memory, so uAgents does not
    write private_keys.json into the working directory; the address changes every run.
    """
    if mailbox and not settings.agent_seed:
        raise ConfigError(SEED_HELP)
    seed = settings.agent_seed
    if seed is None:
        log.warning("MEMORY_AGENT_SEED is not set: local-only agent with a throwaway identity "
                    "(not reachable from Agentverse or ASI:One; the address changes every run)")
        seed = secrets.token_urlsafe(32)  # never printed or stored

    agent = Agent(
        name=settings.agent_name,
        seed=seed,
        port=settings.agent_port,
        mailbox=mailbox,
        endpoint=endpoint,
        resolve=resolve,
        publish_agent_details=True,
        readme_path=str(AGENTVERSE_README),
        description=DESCRIPTION,
    )

    async def answer(question: str) -> str:
        return (await pipeline.answer(question)).text

    agent.include(build_chat_protocol(answer), publish_manifest=True)

    @agent.on_event("startup")
    async def announce(ctx: Context) -> None:
        ctx.logger.info(f"Earmark memory agent ready: data={pipeline.reader.source}, "
                        f"llm={pipeline.chat_model.model if pipeline.chat_model else 'off (keyword router)'}, "
                        f"mailbox={'on' if mailbox else 'off'}")

    @agent.on_event("shutdown")
    async def close(ctx: Context) -> None:
        await pipeline.aclose()

    return agent
