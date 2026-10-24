"""Hub configuration: config/hub.json plus environment overrides.

Precedence (highest first): CLI flags, real environment, repo-root .env, config/hub.json,
the defaults below. Secrets live only in `ConvexEnv` and are never logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[3]
ADAPTER_NAMES = ("simulator", "nfc_serial", "ble_fobs", "camera_stub")


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BusCfg(_Cfg):
    host: str = "127.0.0.1"
    port: int = 8765
    client_queue_max: int = Field(default=1000, ge=10)


class DebounceCfg(_Cfg):
    placement_reads: int = Field(default=2, ge=1)
    removal_s: float = Field(default=1.5, gt=0)
    tick_s: float = Field(default=0.25, gt=0)


class SimulatorCfg(_Cfg):
    poll_s: float = Field(default=0.5, gt=0)
    fob_poll_s: float = Field(default=1.0, gt=0)
    start_delay_s: float = Field(default=1.0, ge=0)
    fob_rssi: dict[str, float] = Field(default_factory=lambda: {"near": -55, "mid": -72, "far": -88})


class NfcCfg(_Cfg):
    port: str | None = None
    port_globs: list[str] = Field(default_factory=lambda: [
        "/dev/cu.usbserial*", "/dev/cu.usbmodem*", "/dev/cu.SLAB_USBtoUART*", "/dev/cu.wchusbserial*",
    ])
    baud: int = 115200
    reconnect_s: float = Field(default=2.0, gt=0)


class FobCfg(_Cfg):
    address: str | None = None
    name: str | None = None


class BleCfg(_Cfg):
    receiver: str = "hub"
    fobs: dict[str, FobCfg] = Field(default_factory=dict)
    ema_tau_s: float = Field(default=2.0, gt=0)
    stale_s: float = Field(default=10.0, gt=0)
    near_dbm: float = -65
    mid_dbm: float = -80
    emit_interval_s: float = Field(default=1.0, ge=0)
    chirp_timeout_s: float = Field(default=10.0, gt=0)
    connect_timeout_s: float = Field(default=10.0, gt=0)
    alert_service_uuid: str = "1802"
    alert_char_uuid: str = "2a06"
    alert_level: int = Field(default=1, ge=1, le=2)
    link_loss_service_uuid: str = "1803"
    link_loss_value: int | None = Field(default=None, ge=0, le=255)


class ConvexCfg(_Cfg):
    registry_poll_s: float = Field(default=2.0, gt=0)
    timeout_s: float = Field(default=3.0, gt=0)
    flush_interval_s: float = Field(default=0.5, gt=0)
    batch_max: int = Field(default=100, ge=1)
    backoff_initial_s: float = Field(default=0.5, gt=0)
    backoff_max_s: float = Field(default=30.0, gt=0)


class HealthCfg(_Cfg):
    interval_s: float = Field(default=5.0, gt=0)


class PathsCfg(_Cfg):
    space: str = "config/space.json"
    seed: str = "config/objects.seed.json"
    cache: str = "config/objects.cache.json"
    queue: str = "var/hub/queue.jsonl"
    trials: str = "var/trials/trials.jsonl"
    logs: str = "logs"


class HubConfig(_Cfg):
    adapters: list[str] = Field(default_factory=lambda: ["simulator"])
    bus: BusCfg = Field(default_factory=BusCfg)
    debounce: DebounceCfg = Field(default_factory=DebounceCfg)
    simulator: SimulatorCfg = Field(default_factory=SimulatorCfg)
    nfc_serial: NfcCfg = Field(default_factory=NfcCfg)
    ble_fobs: BleCfg = Field(default_factory=BleCfg)
    convex: ConvexCfg = Field(default_factory=ConvexCfg)
    health: HealthCfg = Field(default_factory=HealthCfg)
    paths: PathsCfg = Field(default_factory=PathsCfg)

    def path(self, name: str, root: Path = ROOT) -> Path:
        p = Path(getattr(self.paths, name))
        return p if p.is_absolute() else root / p


@dataclass
class ConvexEnv:
    site_url: str
    secret: str = field(repr=False)


def load_dotenv_once(root: Path = ROOT) -> None:
    """Load the repo-root .env without overriding the real environment."""
    from dotenv import load_dotenv

    env = root / ".env"
    if env.is_file():
        load_dotenv(env, override=False)


def parse_adapters(value: str) -> list[str]:
    names = [n.strip() for n in value.split(",") if n.strip()]
    unknown = [n for n in names if n not in ADAPTER_NAMES]
    if unknown:
        raise ValueError(f"unknown adapter(s) {unknown}; choose from {list(ADAPTER_NAMES)}")
    return names


def load_config(path: Path | None = None, env: dict[str, str] | None = None) -> HubConfig:
    """Read hub.json (HUB_CONFIG or config/hub.json) and apply environment overrides."""
    env = dict(os.environ) if env is None else env
    path = path or Path(env.get("HUB_CONFIG") or ROOT / "config" / "hub.json")
    cfg = HubConfig.model_validate_json(path.read_text()) if path.is_file() else HubConfig()
    parse_adapters(",".join(cfg.adapters))
    if env.get("EARMARK_BUS_HOST"):
        cfg.bus.host = env["EARMARK_BUS_HOST"]
    if env.get("EARMARK_BUS_PORT"):
        cfg.bus.port = int(env["EARMARK_BUS_PORT"])
    if env.get("EARMARK_ADAPTERS"):
        cfg.adapters = parse_adapters(env["EARMARK_ADAPTERS"])
    port = env.get("NFC_SERIAL_PORT", "").strip()
    if port and port.lower() != "auto":
        cfg.nfc_serial.port = port
    if env.get("NFC_BAUD"):
        cfg.nfc_serial.baud = int(env["NFC_BAUD"])
    if env.get("HUB_LOG_DIR"):
        cfg.paths.logs = env["HUB_LOG_DIR"]
    return cfg


def convex_env(env: dict[str, str] | None = None) -> tuple[ConvexEnv | None, str]:
    """Convex credentials, or None plus the reason the hub runs offline."""
    env = dict(os.environ) if env is None else env
    url = env.get("CONVEX_SITE_URL", "").strip().rstrip("/")
    secret = env.get("EARMARK_HUB_SECRET", "").strip()
    if not url and not secret:
        return None, "CONVEX_SITE_URL and EARMARK_HUB_SECRET are not set"
    if not url:
        return None, "EARMARK_HUB_SECRET is set but CONVEX_SITE_URL is not"
    if not secret:
        return None, "CONVEX_SITE_URL is set but EARMARK_HUB_SECRET is not"
    return ConvexEnv(site_url=url, secret=secret), ""


def bus_url(env: dict[str, str] | None = None) -> str:
    """URL that bus clients (the CLIs) connect to."""
    env = dict(os.environ) if env is None else env
    if env.get("EARMARK_BUS_URL"):
        return env["EARMARK_BUS_URL"]
    host = env.get("EARMARK_BUS_HOST") or "127.0.0.1"
    port = env.get("EARMARK_BUS_PORT") or "8765"
    return f"ws://{host}:{port}"
