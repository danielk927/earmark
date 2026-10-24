"""Detection adapters. Each turns one detection method into DetectionEvents."""
from __future__ import annotations

from pathlib import Path

from ..clock import Clock
from ..config import HubConfig
from .base import Adapter


def build_adapters(names: list[str], cfg: HubConfig, clock: Clock, *, scenario: Path | None = None,
                   loop: bool = False, step: bool = False, interactive: bool = False) -> list[Adapter]:
    adapters: list[Adapter] = []
    for name in names:
        if name == "simulator":
            from .simulator import SimulatorAdapter

            adapters.append(SimulatorAdapter(clock, cfg.simulator, scenario=scenario, loop=loop, step=step,
                                             interactive=interactive))
        elif name == "nfc_serial":
            from .nfc_serial import NfcSerialAdapter

            adapters.append(NfcSerialAdapter(clock, cfg.nfc_serial, cfg.path("logs")))
        elif name == "ble_fobs":
            from .ble_fobs import BleFobsAdapter

            adapters.append(BleFobsAdapter(clock, cfg.ble_fobs))
        elif name == "camera_stub":
            from .camera_stub import CameraStubAdapter

            adapters.append(CameraStubAdapter())
        else:
            raise ValueError(f"unknown adapter {name!r}")
    return adapters
