"""Settings from the environment (plus a repo-root .env that never overrides real env vars)."""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_DIR.parents[1]
CONFIG_DIR = REPO_ROOT / "config"
AGENTVERSE_README = SERVICE_DIR / "AGENTVERSE_README.md"

DEFAULT_BITDEER_BASE_URL = "https://api-inference.bitdeer.ai/v1"
DEFAULT_BITDEER_AGENT_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash-1017"
DEFAULT_AGENT_NAME = "earmark-memory"
DEFAULT_AGENT_PORT = 8010

# Timeouts and limits (seconds unless noted). Every external call is bounded.
CONVEX_TIMEOUT_S = 5.0
LLM_REQUEST_TIMEOUT_S = 8.0
LLM_TOTAL_BUDGET_S = 20.0
MAX_TOOL_CALLS = 4
LLM_MAX_TOKENS = 500
# Bitdeer chat models reason by default, which costs 9-17 s per call (docs/vendor-notes/bitdeer.md).
LLM_REASONING_EFFORT = "none"
MAX_QUESTION_CHARS = 500

SEED_HELP = (
    "MEMORY_AGENT_SEED is not set, so the agent can't use its Agentverse mailbox (the seed is the agent's identity "
    "and fixes its address). Set it in the repo-root .env to a long random phrase that you keep secret and never "
    "commit, for example the output of:  python3 -c 'import secrets; print(secrets.token_urlsafe(32))'  "
    "Or run locally without a mailbox:  earmark-memory run --no-mailbox"
)


class ConfigError(Exception):
    """A setting is missing or invalid; the message tells the human how to fix it."""


@dataclass(frozen=True)
class Settings:
    convex_site_url: str | None
    read_secret: str | None
    bitdeer_api_key: str | None
    bitdeer_base_url: str
    bitdeer_model: str
    agent_seed: str | None
    agent_name: str
    agent_port: int

    @property
    def llm_enabled(self) -> bool:
        return self.bitdeer_api_key is not None

    @property
    def convex_configured(self) -> bool:
        return self.convex_site_url is not None


def _get(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key, "").strip()
    return value or None


def load_settings(env: Mapping[str, str] | None = None, dotenv_path: Path | None = None) -> Settings:
    """Read settings. With `env=None`, loads `<repo>/.env` (without overriding) and uses os.environ."""
    if env is None:
        path = dotenv_path or REPO_ROOT / ".env"
        if path.is_file():
            load_dotenv(path, override=False)
        env = os.environ

    port_raw = _get(env, "MEMORY_AGENT_PORT")
    try:
        port = int(port_raw) if port_raw else DEFAULT_AGENT_PORT
    except ValueError as exc:
        raise ConfigError(f"MEMORY_AGENT_PORT must be an integer, got {port_raw!r}") from exc
    if not 1 <= port <= 65535:
        raise ConfigError(f"MEMORY_AGENT_PORT must be between 1 and 65535, got {port}")

    return Settings(
        convex_site_url=_get(env, "CONVEX_SITE_URL"),
        read_secret=_get(env, "EARMARK_READ_SECRET"),
        bitdeer_api_key=_get(env, "BITDEER_API_KEY"),
        bitdeer_base_url=_get(env, "BITDEER_BASE_URL") or DEFAULT_BITDEER_BASE_URL,
        bitdeer_model=_get(env, "BITDEER_AGENT_MODEL") or DEFAULT_BITDEER_AGENT_MODEL,
        agent_seed=_get(env, "MEMORY_AGENT_SEED"),
        agent_name=_get(env, "MEMORY_AGENT_NAME") or DEFAULT_AGENT_NAME,
        agent_port=port,
    )
