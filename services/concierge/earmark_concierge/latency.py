"""Per-stage timings as JSON lines in logs/latency.jsonl (summarized by scripts/latency_report.py).

Events: final_transcript, intent, resolve, tool, tts_first_chunk, speech_out, playback.
Each carries `turn` when it belongs to a user turn; `since_final_ms` is measured from
the final transcript of that turn.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)


class LatencyLog:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **fields) -> None:
        rec = {"t": round(time.time(), 3), "event": event,
               **{k: v for k, v in fields.items() if v is not None}}
        if self.path is None:
            return
        try:
            with self.path.open("a") as f:
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        except OSError as e:
            log.warning("latency log write failed: %s", e)
