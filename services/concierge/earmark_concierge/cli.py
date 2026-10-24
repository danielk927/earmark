"""earmark-concierge [run] [--text T] [--repl] [--no-llm] | synth-phrases"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import load_settings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="earmark-concierge", description="Earmark voice concierge.")
    p.add_argument("command", nargs="?", default="run", choices=["run", "synth-phrases"])
    p.add_argument("--text", help="inject one typed transcript after the snapshot arrives, then keep running")
    p.add_argument("--repl", action="store_true", help="read typed transcripts from stdin")
    p.add_argument("--no-llm", action="store_true", help="force the keyword grammar (no Bitdeer)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    for noisy in ("httpx", "httpcore", "openai", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = load_settings()
    if args.no_llm:
        settings.llm_enabled = False

    if args.command == "synth-phrases":
        from .synth import SynthError, synth_phrases
        try:
            paths = synth_phrases(settings)
        except SynthError as e:
            print(f"earmark-concierge synth-phrases: {e}", file=sys.stderr)
            return 2
        print(f"wrote {len(paths)} phrases to {settings.phrases_dir}")
        return 0

    from .app import run
    try:
        asyncio.run(run(settings, text=args.text, repl=args.repl))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
