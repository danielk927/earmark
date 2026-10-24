from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from earmark_contracts import (
    Household,
    Location, ObjectState, RegistryObject, Snapshot, Space, to_dict,
)
from earmark_concierge.app import build
from earmark_concierge.config import REPO_ROOT, Settings

SPACE = Space.model_validate(json.loads((REPO_ROOT / "config" / "space.json").read_text()))
SEED = json.loads((REPO_ROOT / "config" / "objects.seed.json").read_text())
OBJECTS = [RegistryObject.model_validate(o) for o in SEED["objects"]]
SPOT_POS = {s.spot: list(s.position) for s in SPACE.spots}
HOME = {"salt": 2, "sugar": 3, "bp_meds": 4}


def state(oid: str, *, spot: int | None = None, status: str | None = None, precision: str | None = None,
          near: str | None = None, distance_class: str | None = None, area: str | None = None,
          position: list[float] | None = None, last_seen_t: float | None = None) -> ObjectState:
    if spot is not None:
        loc = Location(spot=spot, position=SPOT_POS[spot])
        precision = precision or "exact"
        status = status or "on_spot"
    elif near is not None:
        loc = Location(spot=None, position=[0, 0.6, 0], area=None, near=near, distance_class=distance_class)
        precision = precision or "proximity"
        status = status or "roaming"
    elif area is not None:
        loc = Location(area=area, position=position or [0, 0.6, 0])
        precision = precision or "area"
        status = status or "on_spot"
    else:
        loc = Location(spot=None, position=None)
        precision = precision or "none"
        status = status or "missing"
    home = next((o.home_spot for o in OBJECTS if o.object_id == oid), None)
    return ObjectState(object_id=oid, location=loc, precision=precision, status=status, home_spot=home,
                       last_seen_t=last_seen_t if last_seen_t is not None else time.time(),
                       source="simulator")


def home_states() -> list[ObjectState]:
    """Demo start: salt, sugar, meds on their spots; keys and pepper never seen."""
    return [state(o, spot=s) for o, s in HOME.items()] + [state("keys", last_seen_t=0)]


def snapshot(states: list[ObjectState] | None = None, objects=None) -> Snapshot:
    return Snapshot(household=Household(name="Demo household", timezone="America/Los_Angeles"), space=SPACE, objects=objects or OBJECTS,
                    states=home_states() if states is None else states, registry_version=None)


def make_settings(tmp_path: Path, **kw) -> Settings:
    base = dict(latency_log=tmp_path / "latency.jsonl", say_cmd="true", llm_enabled=False,
                status_interval_s=3600)
    base.update(kw)
    return Settings(**base)


class Harness:
    """A Concierge whose outbound bus messages land in `out` (as schema dicts)."""

    def __init__(self, settings: Settings, mac_app: bool = True) -> None:
        self.out: list[dict] = []
        self.settings = settings

        async def emit(msg) -> None:
            self.out.append(to_dict(msg))

        self.core = build(settings, emit)
        if mac_app:
            self.core._saw_mac_app()

    async def feed(self, *msgs) -> None:
        for m in msgs:
            await self.core.handle(m)
        await self.core.drain()

    async def say(self, text: str) -> list[dict]:
        n = len(self.out)
        await self.core.inject_typed(text)
        await self.core.drain()
        return self.out[n:]

    def of(self, typ: str, msgs: list[dict] | None = None) -> list[dict]:
        return [m for m in (self.out if msgs is None else msgs) if m["type"] == typ]

    @staticmethod
    def spoken(msgs: list[dict]) -> list[str]:
        return [m["text"] for m in msgs if m["type"] in ("speak_text", "speak_cached")
                or (m["type"] == "speak" and m.get("text"))]

    def clear(self) -> None:
        self.out.clear()


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
async def h(settings):
    harness = Harness(settings)
    await harness.feed(snapshot())
    harness.clear()
    return harness
