"""config/space.json: resolve spots, areas, and receivers to positions."""
from __future__ import annotations

from pathlib import Path

from earmark_contracts import Space


class SpaceIndex:
    def __init__(self, space: Space) -> None:
        self.space = space
        self._spots = {s.spot: list(s.position) for s in space.spots}
        self._areas = {a.area: list(a.position) for a in space.areas}
        self._receivers = {r.receiver: (list(r.position) if r.position else None) for r in space.receivers}

    @classmethod
    def load(cls, path: Path) -> "SpaceIndex":
        return cls(Space.model_validate_json(path.read_text()))

    @property
    def spot_numbers(self) -> list[int]:
        return sorted(self._spots)

    def spot_position(self, spot: int) -> list[float] | None:
        return self._spots.get(spot)

    def area_position(self, area: str) -> list[float] | None:
        return self._areas.get(area)

    def receiver_position(self, receiver: str) -> list[float] | None:
        return self._receivers.get(receiver)
