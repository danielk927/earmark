"""Nearby Interaction token relay (docs/UWB-PRD.md 8.1).

Tokens are addressed: each goes only to the client whose hello.device_id equals `to`, never to
the whole bus. The latest token per (from, to) is kept in memory and replayed when the
addressee says hello; `reset` clears nothing (the phones keep their sessions).
"""
from __future__ import annotations

from earmark_contracts import UwbToken


class TokenRelay:
    def __init__(self) -> None:
        self.tokens: dict[tuple[str, str], UwbToken] = {}

    def store(self, msg: UwbToken) -> None:
        self.tokens[(msg.from_, msg.to)] = msg

    def addressed_to(self, device_id: str) -> list[UwbToken]:
        return [m for (_, to), m in self.tokens.items() if to == device_id]
