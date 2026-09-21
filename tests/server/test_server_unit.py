"""Unit tests for src/server — no database, no LLM, no network required.

Run: uv run pytest tests/server -q
"""

import asyncio

import pytest
from fastapi import HTTPException

from server.deps import LOCAL_DEV_USER, apply_cost_caps, auth_mode, get_current_user_id
from server.routers.sessions import _extract_text, _sse


# ---------------------------------------------------------------- cost caps
def test_apply_cost_caps_clamps_out_of_range_values():
    capped = apply_cost_caps(
        {"max_concurrent_research_units": 5, "max_researcher_iterations": 10}
    )
    assert capped["max_concurrent_research_units"] == 1
    assert capped["max_researcher_iterations"] == 2


def test_apply_cost_caps_fills_missing_and_invalid_values():
    filled = apply_cost_caps({})
    assert filled["max_concurrent_research_units"] == 1
    assert filled["max_researcher_iterations"] == 2

    invalid = apply_cost_caps({"max_concurrent_research_units": "abc"})
    assert invalid["max_concurrent_research_units"] == 1


def test_apply_cost_caps_preserves_unrelated_keys():
    out = apply_cost_caps({"research_model": "openai:gpt-4.1"})
    assert out["research_model"] == "openai:gpt-4.1"


# ---------------------------------------------------------------- auth mode
def test_auth_mode_defaults_to_local_without_supabase(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert auth_mode() == "local"


def test_auth_mode_defaults_to_supabase_when_configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert auth_mode() == "supabase"


def test_auth_mode_explicit_override(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("AUTH_MODE", "local")
    assert auth_mode() == "local"


def test_local_mode_accepts_requests_without_header(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local")
    user_id = asyncio.run(get_current_user_id(authorization=None))
    assert user_id == LOCAL_DEV_USER


def test_supabase_mode_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user_id(authorization=None))
    assert exc_info.value.status_code == 401


# ------------------------------------------------------- message/SSE helpers
def test_extract_text_plain_string():
    assert _extract_text("hello") == "hello"


def test_extract_text_content_blocks():
    blocks = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
    assert _extract_text(blocks) == "ab"


def test_extract_text_empty():
    assert _extract_text(None) == ""
    assert _extract_text("") == ""


def test_sse_format_is_parseable():
    raw = _sse("node", {"node": "supervisor"})
    assert raw.startswith("event: node\n")
    assert raw.endswith("\n\n")
    assert '{"node": "supervisor"}' in raw


def test_sse_keeps_unicode():
    raw = _sse("message", {"content": "中文内容"})
    assert "中文内容" in raw


# ---------------------------------------------------------------- .env loading
def test_ensure_env_loaded_reads_env_file(tmp_path, monkeypatch):
    import os

    from server import deps

    env_file = tmp_path / ".env"
    env_file.write_text("ODR_SENTINEL_KEY=loaded_ok\n", encoding="utf-8")
    monkeypatch.setenv("ODR_ENV_FILE", str(env_file))
    monkeypatch.delenv("ODR_SENTINEL_KEY", raising=False)
    monkeypatch.setattr(deps, "_env_loaded", False)

    deps.ensure_env_loaded()

    assert os.environ["ODR_SENTINEL_KEY"] == "loaded_ok"
    monkeypatch.delenv("ODR_SENTINEL_KEY", raising=False)


def test_ensure_env_loaded_does_not_override_existing_env(tmp_path, monkeypatch):
    import os

    from server import deps

    env_file = tmp_path / ".env"
    env_file.write_text("ODR_SENTINEL_KEY=from_file\n", encoding="utf-8")
    monkeypatch.setenv("ODR_ENV_FILE", str(env_file))
    monkeypatch.setenv("ODR_SENTINEL_KEY", "from_shell")
    monkeypatch.setattr(deps, "_env_loaded", False)

    deps.ensure_env_loaded()

    assert os.environ["ODR_SENTINEL_KEY"] == "from_shell"
