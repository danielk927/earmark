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
        elif name == "uwb_sim":
            from ..uwb.sim import UwbSimAdapter

            adapters.append(UwbSimAdapter(clock, cfg.uwb_sim, cfg.uwb, interactive=interactive))
        else:
            raise ValueError(f"unknown adapter {name!r}")
    if interactive:  # one keyboard: the simulator hands the keys it does not use to uwb_sim
        sim = next((a for a in adapters if a.name == "simulator"), None)
        uwb = next((a for a in adapters if a.name == "uwb_sim"), None)
        if sim is not None and uwb is not None:
            sim.opts["extra_keys"] = uwb.key
    return adapters
