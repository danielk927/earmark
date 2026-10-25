"""Settings from the environment.

Every vendor URL, model ID, and voice ID comes from an env var. Defaults are the
values verified in docs/sponsors/vendor-notes/{cartesia,moss}.md. A repo-root
.env is loaded if present, without overriding the real environment. Empty
values count as unset, so a test can blank a key that .env would provide.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _float(name: str, default: float) -> float:
    return float(_get(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(_get(name, str(default)))


def _path(name: str, default: Path) -> Path:
    raw = _get(name)
    if raw is None:
        return default
    p = Path(raw)
    return p if p.is_absolute() else REPO_ROOT / p


@dataclass
class Settings:
    bus_url: str = "ws://127.0.0.1:8765"

    # Cartesia (docs/sponsors/vendor-notes/cartesia.md)
    cartesia_api_key: str | None = None
    cartesia_version: str = "2026-08-14"
    stt_url: str = "wss://api.cartesia.ai/stt/turns/websocket"
    stt_model: str = "ink-2"
    stt_sample_rate: int = 16000
    tts_url: str = "wss://api.cartesia.ai/tts/websocket"
    tts_bytes_url: str = "https://api.cartesia.ai/tts/bytes"
    tts_model: str = "sonic-3.6-2026-08-27"
    voice_id: str | None = None
    tts_encoding: str = "pcm_f32le"
    tts_sample_rate: int = 48000

    # Moss (docs/sponsors/vendor-notes/moss.md)
    moss_project_id: str | None = None
    moss_project_key: str | None = None
    moss_index_name: str = "earmark-objects"

    # Anthropic (Claude picks the tool for each request)
    anthropic_api_key: str | None = None
    anthropic_chat_model: str = "claude-haiku-5-5"
    llm_timeout_s: float = 1.5
    llm_enabled: bool = True  # --no-llm sets this False

    # Concierge tuning (CONCIERGE_*)
    stt_connect_timeout_s: float = 1.0
    stt_first_event_timeout_s: float = 1.5
    stt_idle_close_s: float = 5.0
    stt_probe_interval_s: float = 60.0
    tts_first_chunk_timeout_s: float = 1.0
    guide_timeout_s: float = 60.0
    behind_cooldown_s: float = 4.0
    status_interval_s: float = 5.0
    mac_app_ttl_s: float = 15.0
    label_window_s: float = 300.0
    clarify_window_s: float = 30.0
    stale_s: float = 600.0
    say_cmd: str = "say"
    timezone: str | None = None
    moss_min_score: float = 0.35
    moss_margin: float = 0.08

    phrases_path: Path = field(default_factory=lambda: REPO_ROOT / "config" / "phrases.json")
    phrases_dir: Path = field(default_factory=lambda: REPO_ROOT / "config" / "phrases")
    registry_paths: tuple[Path, ...] = field(default_factory=lambda: (
        REPO_ROOT / "config" / "objects.cache.json",
        REPO_ROOT / "config" / "objects.seed.json",
    ))
    latency_log: Path = field(default_factory=lambda: REPO_ROOT / "logs" / "latency.jsonl")

    @property
    def cartesia_enabled(self) -> bool:
        return bool(self.cartesia_api_key)

    @property
    def tts_enabled(self) -> bool:
        return bool(self.cartesia_api_key and self.voice_id)

    @property
    def moss_enabled(self) -> bool:
        return bool(self.moss_project_id and self.moss_project_key)

    @property
    def anthropic_enabled(self) -> bool:
        return bool(self.llm_enabled and self.anthropic_api_key)


def load_settings(*, dotenv: bool = True) -> Settings:
    if dotenv:
        load_dotenv(REPO_ROOT / ".env", override=False)
    d = Settings()
    return Settings(
        bus_url=_get("EARMARK_BUS_URL", d.bus_url),
        cartesia_api_key=_get("CARTESIA_API_KEY"),
        cartesia_version=_get("CARTESIA_VERSION", d.cartesia_version),
        stt_url=_get("CARTESIA_STT_URL", d.stt_url),
        stt_model=_get("CARTESIA_STT_MODEL", d.stt_model),
        stt_sample_rate=_int("CARTESIA_STT_SAMPLE_RATE", d.stt_sample_rate),
        tts_url=_get("CARTESIA_TTS_URL", d.tts_url),
        tts_bytes_url=_get("CARTESIA_TTS_BYTES_URL", d.tts_bytes_url),
        tts_model=_get("CARTESIA_TTS_MODEL", d.tts_model),
        voice_id=_get("CARTESIA_VOICE_ID"),
        tts_encoding=_get("CARTESIA_TTS_ENCODING", d.tts_encoding),
        tts_sample_rate=_int("CARTESIA_TTS_SAMPLE_RATE", d.tts_sample_rate),
        moss_project_id=_get("MOSS_PROJECT_ID"),
        moss_project_key=_get("MOSS_PROJECT_KEY"),
        moss_index_name=_get("MOSS_INDEX_NAME", d.moss_index_name),
        anthropic_api_key=_get("ANTHROPIC_API_KEY"),
        anthropic_chat_model=_get("ANTHROPIC_CHAT_MODEL", d.anthropic_chat_model),
        llm_timeout_s=_float("LLM_TIMEOUT_S", d.llm_timeout_s),
        stt_connect_timeout_s=_float("CONCIERGE_STT_CONNECT_TIMEOUT_S", d.stt_connect_timeout_s),
        stt_first_event_timeout_s=_float("CONCIERGE_STT_FIRST_EVENT_TIMEOUT_S", d.stt_first_event_timeout_s),
        stt_idle_close_s=_float("CONCIERGE_STT_IDLE_CLOSE_S", d.stt_idle_close_s),
        stt_probe_interval_s=_float("CONCIERGE_STT_PROBE_INTERVAL_S", d.stt_probe_interval_s),
        tts_first_chunk_timeout_s=_float("CONCIERGE_TTS_FIRST_CHUNK_TIMEOUT_S", d.tts_first_chunk_timeout_s),
        guide_timeout_s=_float("CONCIERGE_GUIDE_TIMEOUT_S", d.guide_timeout_s),
        behind_cooldown_s=_float("CONCIERGE_BEHIND_COOLDOWN_S", d.behind_cooldown_s),
        status_interval_s=_float("CONCIERGE_STATUS_INTERVAL_S", d.status_interval_s),
        mac_app_ttl_s=_float("CONCIERGE_MAC_APP_TTL_S", d.mac_app_ttl_s),
        label_window_s=_float("CONCIERGE_LABEL_WINDOW_S", d.label_window_s),
        clarify_window_s=_float("CONCIERGE_CLARIFY_WINDOW_S", d.clarify_window_s),
        stale_s=_float("CONCIERGE_STALE_S", d.stale_s),
        say_cmd=_get("CONCIERGE_SAY_CMD", d.say_cmd),
        timezone=_get("CONCIERGE_TIMEZONE"),
        moss_min_score=_float("CONCIERGE_MOSS_MIN_SCORE", d.moss_min_score),
        moss_margin=_float("CONCIERGE_MOSS_MARGIN", d.moss_margin),
        latency_log=_path("CONCIERGE_LATENCY_LOG", d.latency_log),
    )
