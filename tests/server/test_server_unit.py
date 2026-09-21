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


# ---------------------------------------------------------------- health
def _health_app(db_ready: bool, graph_ready: bool):
    """Minimal app with only the health router (no lifespan -> fully offline)."""
    from fastapi import FastAPI

    from server.routers.health import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.db_ready = db_ready
    app.state.graph_ready = graph_ready
    return app


def test_health_returns_200_when_ready():
    from fastapi.testclient import TestClient

    with TestClient(_health_app(True, True)) as client:
        res = client.get("/api/health")

    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["db"] is True
    assert res.json()["graph"] is True


def test_health_returns_503_when_graph_not_ready():
    from fastapi.testclient import TestClient

    with TestClient(_health_app(True, False)) as client:
        res = client.get("/api/health")

    assert res.status_code == 503
    assert res.json()["status"] == "degraded"
    assert res.json()["graph"] is False


def test_health_returns_503_when_db_not_ready():
    from fastapi.testclient import TestClient

    with TestClient(_health_app(False, True)) as client:
        res = client.get("/api/health")

    assert res.status_code == 503
    assert res.json()["db"] is False


# ---------------------------------------------------------------- checkpointer DSN
def test_checkpointer_dsn_strips_asyncpg_and_adds_connect_timeout(monkeypatch):
    from server import db

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:nodr@127.0.0.1:5433/nodr"
    )
    assert db.checkpointer_dsn() == (
        "postgresql://postgres:nodr@127.0.0.1:5433/nodr?connect_timeout=10"
    )


def test_checkpointer_dsn_appends_to_existing_query_string(monkeypatch):
    from server import db

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d?sslmode=require"
    )
    assert db.checkpointer_dsn() == (
        "postgresql://u:p@h:5432/d?sslmode=require&connect_timeout=10"
    )


def test_checkpointer_dsn_keeps_an_explicit_timeout(monkeypatch):
    from server import db

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d?connect_timeout=30"
    )
    assert db.checkpointer_dsn() == "postgresql://u:p@h:5432/d?connect_timeout=30"


def test_checkpointer_dsn_is_none_without_database_url(monkeypatch):
    from server import db

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.checkpointer_dsn() is None


# ---------------------------------------------------------------- astream mapping
def test_map_updates_root_report():
    from server.routers.sessions import _map_stream_item

    frames, report = _map_stream_item(
        (), "updates", {"final_report_generation": {"final_report": "R"}}, {}
    )
    assert frames == [("node", {"node": "final_report_generation", "subgraph": False})]
    assert report == "R"


def test_map_updates_subgraph_node_emitted():
    from server.routers.sessions import _map_stream_item

    frames, report = _map_stream_item(
        ("researcher:abc",), "updates", {"compress_research": {}}, {}
    )
    assert frames == [
        (
            "node",
            {
                "node": "compress_research",
                "subgraph": True,
                "namespace": "researcher:abc",
            },
        )
    ]
    assert report is None


def test_map_messages_collects_usage_and_text():
    from langchain_core.messages import AIMessage

    from server.routers.sessions import _map_stream_item

    usage: dict = {}
    chunk = AIMessage(
        content="hello",
        id="m1",
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    frames, report = _map_stream_item(
        (), "messages", (chunk, {"langgraph_node": "supervisor"}), usage
    )

    assert frames == [
        ("message", {"node": "supervisor", "content": "hello", "subgraph": False})
    ]
    assert usage[("supervisor", "m1")]["total"] == 15
    assert report is None


def test_map_messages_usage_keyed_per_message_not_overwritten():
    from langchain_core.messages import AIMessage

    from server.routers.sessions import _map_stream_item

    def chunk(msg_id: str, total: int) -> AIMessage:
        return AIMessage(
            content="",
            id=msg_id,
            usage_metadata={"input_tokens": 1, "output_tokens": total - 1, "total_tokens": total},
        )

    usage: dict = {}
    meta = {"langgraph_node": "researcher"}
    for item in (chunk("m1", 10), chunk("m2", 20), chunk("m1", 30)):
        _map_stream_item((), "messages", (item, meta), usage)

    assert set(usage) == {("researcher", "m1"), ("researcher", "m2")}
    assert usage[("researcher", "m1")]["total"] == 30  # last chunk for m1 wins
    assert usage[("researcher", "m2")]["total"] == 20  # m2 untouched


def test_map_messages_derives_output_tokens_from_total():
    from langchain_core.messages import AIMessage

    from server.routers.sessions import _map_stream_item

    usage: dict = {}
    # langchain requires all three usage keys, so the realistic "provider
    # reported no output tokens" shape is output_tokens == 0 next to a larger
    # total_tokens.
    chunk = AIMessage(
        content="x",
        id="m1",
        usage_metadata={"input_tokens": 10, "output_tokens": 0, "total_tokens": 25},
    )
    _map_stream_item((), "messages", (chunk, {"langgraph_node": "researcher"}), usage)

    assert usage[("researcher", "m1")]["output"] == 15
    assert usage[("researcher", "m1")]["total"] == 25


def test_map_messages_in_subgraph_is_tagged():
    from langchain_core.messages import AIMessage

    from server.routers.sessions import _map_stream_item

    chunk = AIMessage(content="from a subgraph", id="m1")
    frames, _ = _map_stream_item(
        ("researcher:abc",), "messages", (chunk, {"langgraph_node": "researcher"}), {}
    )

    assert frames == [
        (
            "message",
            {
                "node": "researcher",
                "content": "from a subgraph",
                "subgraph": True,
                "namespace": "researcher:abc",
            },
        )
    ]
