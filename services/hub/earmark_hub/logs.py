"""Logging: JSON lines to logs/<name>.jsonl plus a short human line on stderr."""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

_STD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def _extras(record: logging.LogRecord) -> dict:
    return {k: v for k, v in vars(record).items() if k not in _STD}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"t": round(record.created, 3), "level": record.levelname, "logger": record.name,
                 "msg": record.getMessage(), **_extras(record)}
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, separators=(",", ":"))


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        stamp = time.strftime("%H:%M:%S", time.localtime(record.created)) + f".{int(record.msecs):03d}"
        extras = " ".join(f"{k}={v}" for k, v in _extras(record).items())
        line = f"{stamp} {record.levelname[0]} {record.name.removeprefix('earmark.')}: {record.getMessage()}"
        line += f" {extras}" if extras else ""
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def setup_logging(log_dir: Path | None, name: str, console_level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(console_level)
    console.setFormatter(ConsoleFormatter())
    root.addHandler(console)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        f = logging.FileHandler(log_dir / f"{name}.jsonl")
        f.setLevel(logging.DEBUG)
        f.setFormatter(JsonFormatter())
        root.addHandler(f)
    for noisy in ("websockets", "httpx", "httpcore", "bleak", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
