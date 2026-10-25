from __future__ import annotations

import pytest

from earmark_memory.config import ConfigError, load_settings
from earmark_memory.fixture import FixtureConvexReader
from earmark_memory.pipeline import build_pipeline


def test_defaults_and_blank_values():
    s = load_settings({"ANTHROPIC_API_KEY": "  ", "MEMORY_AGENT_SEED": ""})
    assert (s.convex_site_url, s.read_secret, s.anthropic_api_key, s.agent_seed) == (None, None, None, None)
    assert s.anthropic_model == "claude-sonnet-5-5"
    assert (s.agent_name, s.agent_port) == ("earmark-memory", 8010)
    assert not s.llm_enabled and not s.convex_configured


def test_bad_port():
    with pytest.raises(ConfigError, match="MEMORY_AGENT_PORT"):
        load_settings({"MEMORY_AGENT_PORT": "eighty"})


def test_dotenv_never_overrides_the_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("MEMORY_AGENT_NAME=from-dotenv\nMEMORY_AGENT_PORT=8099\n")
    monkeypatch.setenv("MEMORY_AGENT_NAME", "from-env")
    monkeypatch.delenv("MEMORY_AGENT_PORT", raising=False)  # also restores it after load_dotenv sets it
    s = load_settings(dotenv_path=env_file)
    assert (s.agent_name, s.agent_port) == ("from-env", 8099)


def test_fakes_are_chosen_when_keys_are_missing():
    p = build_pipeline(load_settings({}))
    assert isinstance(p.reader, FixtureConvexReader) and p.chat_model is None
    p = build_pipeline(load_settings({"ANTHROPIC_API_KEY": "sk-x"}), use_llm=True)
    assert p.chat_model is not None and p.chat_model.model == "claude-sonnet-5-5"


def test_convex_url_without_secret_is_an_error():
    with pytest.raises(ConfigError, match="EARMARK_READ_SECRET"):
        build_pipeline(load_settings({"CONVEX_SITE_URL": "https://x.convex.site"}))
