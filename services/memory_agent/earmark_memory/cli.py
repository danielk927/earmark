"""`earmark-memory`: ask a question locally, run the uAgent, print the address, or serve the fixture."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import SEED_HELP, ConfigError, load_settings

log = logging.getLogger("earmark.memory")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def _ask(question: str, fixture: bool, use_llm: bool) -> int:
    from .pipeline import build_pipeline

    pipeline = build_pipeline(load_settings(), fixture=fixture, use_llm=use_llm)
    try:
        result = await pipeline.answer(question)
    finally:
        await pipeline.aclose()
    print(result.text)
    return 0


def _run(fixture: bool, no_mailbox: bool) -> int:
    from .agent import build_agent
    from .pipeline import build_pipeline

    settings = load_settings()
    if not settings.agent_seed and not (no_mailbox or fixture):
        raise ConfigError(SEED_HELP)
    mailbox = bool(settings.agent_seed) and not no_mailbox
    pipeline = build_pipeline(settings, fixture=fixture)
    agent = build_agent(settings, pipeline, mailbox=mailbox)
    log.info(
        "agent %s address %s (port %d, mailbox %s)",
        settings.agent_name,
        agent.address,
        settings.agent_port,
        "on" if mailbox else "off",
    )
    agent.run()
    return 0


def _address() -> int:
    from uagents_core.identity import Identity

    seed = load_settings().agent_seed
    if not seed:
        raise ConfigError(SEED_HELP)
    print(Identity.from_seed(seed, 0).address)
    return 0


def _fixture_server(port: int) -> int:
    from .fixture import FixtureData, FixtureServer

    secret = load_settings().read_secret
    if not secret:
        raise ConfigError("Set EARMARK_READ_SECRET (any value) so the fixture server can check the X-Earmark-Secret header.")
    server = FixtureServer(FixtureData(), secret, port=port)
    log.info("fixture Convex serving %s (point CONVEX_SITE_URL here, same EARMARK_READ_SECRET); Ctrl-C to stop", server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="earmark-memory", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ask = sub.add_parser("ask", help="answer one question locally (same pipeline as the agent)")
    ask.add_argument("question")
    ask.add_argument("--fixture", action="store_true", help="use the offline fixture even if CONVEX_SITE_URL is set")
    ask.add_argument("--no-llm", action="store_true", help="skip Bitdeer and use the keyword router")

    run = sub.add_parser("run", help="start the uAgent (mailbox on when MEMORY_AGENT_SEED is set)")
    run.add_argument(
        "--fixture", action="store_true", help="answer from the offline fixture (implies --no-mailbox without a seed)"
    )
    run.add_argument("--no-mailbox", action="store_true", help="local only: no Agentverse mailbox")

    sub.add_parser("address", help="print the agent address derived from MEMORY_AGENT_SEED")

    fx = sub.add_parser("fixture-server", help="serve the fixture over HTTP with the Convex read routes")
    fx.add_argument("--port", type=int, default=8011)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        if args.cmd == "ask":
            return asyncio.run(_ask(args.question, args.fixture, not args.no_llm))
        if args.cmd == "run":
            return _run(args.fixture, args.no_mailbox)
        if args.cmd == "address":
            return _address()
        return _fixture_server(args.port)
    except (ConfigError, ValueError) as exc:
        print(f"earmark-memory: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
