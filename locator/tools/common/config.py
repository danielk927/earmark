"""Config loaders (LOCATOR_BRIEF.md sections 2.2, 4.6, 8.6).

Beacon-config import rule (brief section 2.2): the app and tools accept
either a bare ``{"beacons": [...]}`` file or the other repo's full
space.json, reading only its ``beacons`` key and ignoring everything else.

Chirp config (brief section 4.6): the bare JSON object is the single source
of truth; a file that wraps it under a ``"chirp"`` key (e.g. the full
locator_params.json) is also accepted.

All loaders take a path argument and fall back to in-code defaults when the
path is None, so every consumer works before any config file exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chirp import ChirpConfig

class ConfigError(ValueError):
    """Raised when a config file violates the brief's contracts."""


@dataclass(frozen=True)
class Beacon:
    """One acoustic beacon: id, room-frame position [m], schedule slot."""

    id: str
    position: tuple[float, float, float]
    slot: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "position": [float(self.position[0]), float(self.position[1]), float(self.position[2])],
            "slot": int(self.slot),
        }


#: Placeholder geometry from brief section 2.2 (real values are taped in
#: Phase C). Positions are [x, y, z] meters in the room frame.
DEFAULT_BEACONS: tuple[Beacon, ...] = (
    Beacon("B1", (-1.5, 1.5, 1.8), 0),
    Beacon("B2", (1.5, 1.5, 0.3), 1),
    Beacon("B3", (1.5, -1.5, 1.8), 2),
    Beacon("B4", (-1.5, -1.5, 0.3), 3),
    Beacon("B5", (-1.8, 0.0, 1.0), 4),
)


def beacons_from_dict(data: dict[str, Any]) -> tuple[Beacon, ...]:
    """Validate a parsed beacon-config dict (bare or space.json)."""
    if not isinstance(data, dict):
        raise ConfigError("beacon config must be a JSON object")
    raw = data.get("beacons")
    if raw is None:
        raise ConfigError(
            "beacon config has no 'beacons' key (brief section 2.2 import rule: "
            "accepts a bare {\"beacons\": [...]} file or the other repo's space.json)"
        )
    if not isinstance(raw, list) or not raw:
        raise ConfigError("'beacons' must be a non-empty list")

    beacons: list[Beacon] = []
    seen_ids: set[str] = set()
    seen_slots: set[int] = set()
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"beacons[{i}] must be an object")
        beacon_id = entry.get("id")
        if not isinstance(beacon_id, str) or not beacon_id:
            raise ConfigError(f"beacons[{i}].id must be a non-empty string")
        position = entry.get("position")
        if not isinstance(position, list) or len(position) != 3:
            raise ConfigError(f"beacons[{i}].position must be a list of 3 numbers")
        slot = entry.get("slot")
        if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
            raise ConfigError(f"beacons[{i}].slot must be a non-negative integer")
        if beacon_id in seen_ids:
            raise ConfigError(f"duplicate beacon id {beacon_id!r}")
        if slot in seen_slots:
            raise ConfigError(f"duplicate slot {slot} on beacon {beacon_id!r}")
        try:
            position_t = (float(position[0]), float(position[1]), float(position[2]))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"beacons[{i}].position must contain numbers") from exc
        seen_ids.add(beacon_id)
        seen_slots.add(slot)
        beacons.append(Beacon(beacon_id, position_t, slot))
    return tuple(sorted(beacons, key=lambda b: b.slot))


def load_beacon_config(path: str | Path | None = None) -> tuple[Beacon, ...]:
    """Load beacons from ``path`` (bare file or full space.json), or defaults.

    The import rule (brief section 2.2) reads only the ``beacons`` key of the
    file and ignores every other key.
    """
    if path is None:
        return DEFAULT_BEACONS
    data = _read_json(Path(path))
    return beacons_from_dict(data)


_CHIRP_FIELDS = {
    "f_lo": float,
    "f_hi": float,
    "length_ms": float,
    "slot_ms": float,
    "n_slots": int,
    "version": int,
}


def chirp_from_dict(data: dict[str, Any]) -> ChirpConfig:
    """Validate a parsed chirp-config dict into a ChirpConfig."""
    if not isinstance(data, dict):
        raise ConfigError("chirp config must be a JSON object")
    unknown = sorted(set(data) - set(_CHIRP_FIELDS) - {"marker", "others_direction"})
    if unknown:
        raise ConfigError(f"unknown chirp config key(s): {', '.join(unknown)}")
    kwargs: dict[str, Any] = {}
    for key, cast in _CHIRP_FIELDS.items():
        if key in data:
            try:
                kwargs[key] = cast(data[key])
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"chirp config {key}={data[key]!r} is not {cast}") from exc
    marker = data.get("marker")
    if marker is not None:
        if not isinstance(marker, dict) or set(marker) != {"beacon", "direction"}:
            raise ConfigError("chirp config 'marker' must be {beacon, direction}")
        kwargs["marker_beacon"] = marker["beacon"]
        kwargs["marker_direction"] = marker["direction"]
    if "others_direction" in data:
        kwargs["others_direction"] = data["others_direction"]
    try:
        return ChirpConfig(**kwargs)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def load_chirp_config(path: str | Path | None = None) -> ChirpConfig:
    """Load the chirp config from ``path``, or the section 4.6 defaults.

    Accepts the bare section 4.6 JSON object, or a file wrapping it under a
    top-level ``"chirp"`` key (e.g. the full locator_params.json).
    """
    if path is None:
        return ChirpConfig()
    data = _read_json(Path(path))
    if isinstance(data, dict) and isinstance(data.get("chirp"), dict):
        data = data["chirp"]
    return chirp_from_dict(data)


def _read_json(path: Path) -> Any:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
