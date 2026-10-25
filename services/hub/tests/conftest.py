from __future__ import annotations

import shutil
import socket
from pathlib import Path

import pytest
from earmark_contracts import DetectionEvent, Registry

from earmark_hub.adapters.simulator import Simulator, load_scenario
from earmark_hub.clock import VirtualClock
from earmark_hub.config import HubConfig
from earmark_hub.space import SpaceIndex
from earmark_hub.state import StateEngine

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"  # pinned geometry: config/space.json gets re-measured
T0 = 1_761_350_400.0

SALT, SUGAR, PEPPER, MEDS, UNKNOWN = ("04A1B2C3D4E501", "04A1B2C3D4E502", "04A1B2C3D4E503", "04A1B2C3D4E504",
                                     "04A1B2C3D4E5FF")


@pytest.fixture
def space() -> SpaceIndex:
    return SpaceIndex.load(FIXTURES / "space.json")


@pytest.fixture
def objects():
    return Registry.model_validate_json((ROOT / "config" / "objects.seed.json").read_text()).objects


@pytest.fixture
def engine(space, objects) -> StateEngine:
    return StateEngine(space, objects)


def read(spot: int, tag: str | None, t: float, source: str = "simulator") -> DetectionEvent:
    if tag is None:
        return DetectionEvent(source=source, tag="EMPTY", kind="removed", where={"spot": spot},
                              precision="exact", rssi=None, t=T0 + t)
    return DetectionEvent(source=source, tag=tag, kind="seen", where={"spot": spot}, precision="exact",
                          rssi=None, t=T0 + t)


def fob(distance_class: str | None, t: float, rssi: float | None = -70.0, tag: str = "fob_keys") -> DetectionEvent:
    if distance_class is None:
        return DetectionEvent(source="ble", tag=tag, kind="lost", where=None, precision="none", rssi=None, t=T0 + t)
    return DetectionEvent(source="ble", tag=tag, kind="seen", where={"near": "hub", "distance_class": distance_class},
                          precision="proximity", rssi=rssi, t=T0 + t)


async def run_scenario(name: str, space: SpaceIndex, objects):
    """Simulator + state engine on a virtual clock. Returns (engine, engine outputs, non-detection lines)."""
    clock = VirtualClock(T0)
    sim = Simulator(clock, objects=objects, spots=space.spot_numbers,
                    scenario=load_scenario(ROOT / "scenarios" / f"{name}.jsonl"))
    eng = StateEngine(space, objects)
    outputs, others = [], []

    async def emit(msg) -> None:
        outputs.extend(eng.tick(clock.now()))
        if isinstance(msg, DetectionEvent):
            outputs.extend(eng.handle(msg))
        else:
            others.append(msg)

    await sim.run(emit)
    outputs.extend(eng.tick(clock.now() + 10))
    return eng, outputs, others


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def hub_root(tmp_path) -> Path:
    """A throwaway repo root with the pinned space fixture and the real seed config, so tests never touch config/ or var/."""
    (tmp_path / "config").mkdir()
    shutil.copy(FIXTURES / "space.json", tmp_path / "config" / "space.json")
    shutil.copy(ROOT / "config" / "objects.seed.json", tmp_path / "config" / "objects.seed.json")
    return tmp_path


@pytest.fixture
def hub_cfg() -> HubConfig:
    cfg = HubConfig()
    cfg.bus.port = 0
    cfg.health.interval_s = 3600
    return cfg
