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


# ---------------------------------------------------------------- run settlement
class _FakeGraph:
    """Minimal stand-in for the compiled graph: no DB, no LLM, no network."""

    def __init__(self, items=(), state=None):
        self._items = list(items)
        self._state = (
            state if state is not None else {"messages": [], "research_brief": None}
        )

    async def astream(self, inputs, config, **kwargs):
        for item in self._items:
            yield item

    async def aget_state(self, config):
        from types import SimpleNamespace

        return SimpleNamespace(values=self._state)


class _BoomGraph(_FakeGraph):
    """Graph whose stream fails immediately."""

    async def astream(self, inputs, config, **kwargs):
        raise ValueError("boom")
        yield  # pragma: no cover — makes this an async generator


def _parse_frame(raw: str) -> tuple[str, dict]:
    """Parse one SSE frame produced by ``_sse`` back into (event, data)."""
    import json

    lines = raw.strip().split("\n")
    return lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))


def _patch_settlement(monkeypatch) -> list[dict]:
    """Capture settlements instead of touching the database."""
    from server.routers import sessions as S

    calls: list[dict] = []

    async def fake_archive(session_id, *, status, **kwargs):
        calls.append({"session_id": session_id, "status": status, **kwargs})

    async def fake_record_usage(user_id, thread_id, aggregated):
        return None

    monkeypatch.setattr(S, "_archive", fake_archive)
    monkeypatch.setattr(S, "_record_usage", fake_record_usage)
    return calls


async def _collect(agen) -> list[str]:
    return [frame async for frame in agen]


def test_terminal_status_set_includes_cancelled():
    from server.routers.sessions import TERMINAL_STATUSES

    assert {"awaiting_input", "completed", "failed", "cancelled"} <= set(
        TERMINAL_STATUSES
    )


def test_stream_frames_archives_completed_and_emits_done(monkeypatch):
    from server.routers import sessions as S

    calls = _patch_settlement(monkeypatch)
    graph = _FakeGraph(
        items=[((), "updates", {"final_report_generation": {"final_report": "R"}})]
    )

    frames = asyncio.run(
        _collect(
            S._stream_frames(
                graph=graph,
                inputs={},
                config={},
                session_id="s1",
                user_id="u1",
                run_timeout=0,
                lock=None,
            )
        )
    )

    assert [_parse_frame(f)[0] for f in frames] == ["node", "done"]
    done = _parse_frame(frames[-1])[1]
    assert done["status"] == "completed"
    assert done["final_report"] == "R"
    assert [c["status"] for c in calls] == ["completed"]


def test_stream_frames_archives_failed_on_exception(monkeypatch):
    from server.routers import sessions as S

    calls = _patch_settlement(monkeypatch)

    frames = asyncio.run(
        _collect(
            S._stream_frames(
                graph=_BoomGraph(),
                inputs={},
                config={},
                session_id="s1",
                user_id="u1",
                run_timeout=0,
                lock=None,
            )
        )
    )

    assert [_parse_frame(f)[0] for f in frames] == ["error"]
    assert [c["status"] for c in calls] == ["failed"]
    assert calls[0]["error_message"] == "boom"


def test_stream_frames_archives_cancelled_on_client_disconnect(monkeypatch):
    """A closed stream must not leave the session stuck in "running"."""
    import contextlib

    from server.routers import sessions as S

    calls = _patch_settlement(monkeypatch)
    graph = _FakeGraph(items=[((), "updates", {"supervisor": {}})])

    async def drive():
        gen = S._stream_frames(
            graph=graph,
            inputs={},
            config={},
            session_id="s1",
            user_id="u1",
            run_timeout=0,
            lock=None,
        )
        first = await gen.__anext__()
        # Starlette closes the body generator this way when the client is gone.
        with contextlib.suppress(StopAsyncIteration, GeneratorExit):
            await gen.athrow(GeneratorExit)
        return first

    first = asyncio.run(drive())

    assert first.startswith("event: node\n")
    assert [c["status"] for c in calls] == ["cancelled"]


def test_stream_frames_releases_the_lock(monkeypatch):
    from server.routers import sessions as S

    _patch_settlement(monkeypatch)
    lock = asyncio.Lock()

    async def drive():
        await lock.acquire()
        frames = await _collect(
            S._stream_frames(
                graph=_FakeGraph(
                    items=[((), "updates", {"final_report_generation": {"final_report": "R"}})]
                ),
                inputs={},
                config={},
                session_id="s1",
                user_id="u1",
                run_timeout=0,
                lock=lock,
            )
        )
        return frames

    asyncio.run(drive())

    assert lock.locked() is False


# ------------------------------------------------------------- same-session mutex
class _HeldLock:
    """Stand-in for a lock that another in-flight run already holds."""

    def locked(self) -> bool:
        return True

    async def acquire(self) -> bool:  # pragma: no cover — never reached
        raise AssertionError("must not acquire an already-held lock")

    def release(self) -> None:  # pragma: no cover — never reached
        raise AssertionError("must not release a lock this request never took")


def _sessions_app(monkeypatch, graph=None) -> tuple:
    """Minimal app with only the sessions router: no lifespan, no DB, no LLM."""
    from types import SimpleNamespace

    from fastapi import FastAPI

    from server import graphs
    from server.routers import sessions as S

    monkeypatch.setenv("AUTH_MODE", "local")
    calls: list[dict] = []

    async def fake_get_session(user_id, session_id):
        return SimpleNamespace(
            id=session_id, user_id=user_id, question="q", status="created",
            research_brief=None, final_report=None,
        )

    async def fake_archive(session_id, *, status, **kwargs):
        calls.append({"session_id": session_id, "status": status, **kwargs})

    async def fake_record_usage(user_id, thread_id, aggregated):
        return None

    monkeypatch.setattr(S, "_get_session", fake_get_session)
    monkeypatch.setattr(S, "_archive", fake_archive)
    monkeypatch.setattr(S, "_record_usage", fake_record_usage)
    monkeypatch.setattr(graphs.manager, "graph", graph or _FakeGraph(), raising=False)

    app = FastAPI()
    app.include_router(S.router, prefix="/api/sessions")
    return app, calls


def test_session_lock_registry_is_per_thread():
    from server.routers.sessions import _lock_for

    assert _lock_for("a") is _lock_for("a")
    assert _lock_for("a") is not _lock_for("b")


def test_concurrent_run_on_same_session_is_rejected(monkeypatch):
    from fastapi.testclient import TestClient

    from server.routers import sessions as S

    app, calls = _sessions_app(monkeypatch)
    monkeypatch.setattr(S, "_lock_for", lambda thread_id: _HeldLock())

    with TestClient(app) as client:
        res = client.post("/api/sessions/s1/runs/stream", json={})

    assert res.status_code == 409
    assert "in progress" in res.json()["detail"]
    # A rejected request must not touch the session state.
    assert calls == []


def test_run_stream_returns_sse_and_releases_the_lock(monkeypatch):
    from fastapi.testclient import TestClient

    from server.routers import sessions as S

    app, calls = _sessions_app(
        monkeypatch,
        graph=_FakeGraph(
            items=[((), "updates", {"final_report_generation": {"final_report": "R"}})]
        ),
    )

    with TestClient(app) as client:
        res = client.post("/api/sessions/free-session/runs/stream", json={})

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert "event: done" in res.text
    assert [c["status"] for c in calls] == ["running", "completed"]
    # Released once the stream finished, so the session can be run again.
    assert S._lock_for("free-session").locked() is False


# ------------------------------------------------------- token quota & wall clock
class _SlowGraph(_FakeGraph):
    """Graph that never produces a frame in time."""

    async def astream(self, inputs, config, **kwargs):
        await asyncio.sleep(5)
        yield ((), "updates", {})  # pragma: no cover — cancelled by the timeout


def test_enforce_token_quota_is_disabled_by_default(monkeypatch):
    from server.deps import enforce_token_quota

    monkeypatch.delenv("MAX_TOKENS_PER_USER_PER_DAY", raising=False)
    asyncio.run(enforce_token_quota("u1"))  # must not raise


def test_enforce_token_quota_allows_usage_under_the_limit(monkeypatch):
    from server import deps
    from server.deps import enforce_token_quota

    async def fake_used(user_id: str) -> int:
        return 10

    monkeypatch.setattr(deps, "_tokens_used_today", fake_used)
    monkeypatch.setenv("MAX_TOKENS_PER_USER_PER_DAY", "1000")
    asyncio.run(enforce_token_quota("u1"))  # must not raise


def test_enforce_token_quota_raises_429_over_the_limit(monkeypatch):
    from server import deps
    from server.deps import enforce_token_quota

    async def fake_used(user_id: str) -> int:
        return 10**9

    monkeypatch.setattr(deps, "_tokens_used_today", fake_used)
    monkeypatch.setenv("MAX_TOKENS_PER_USER_PER_DAY", "1000")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(enforce_token_quota("u1"))

    assert exc_info.value.status_code == 429


def test_tokens_used_today_degrades_to_zero_without_a_database():
    """No DATABASE_URL / unstarted engine must not raise — it means "no usage"."""
    from server.deps import _tokens_used_today

    assert asyncio.run(_tokens_used_today("u1")) == 0


def test_run_timeout_seconds_parsing(monkeypatch):
    from server.routers.sessions import _run_timeout_seconds

    monkeypatch.delenv("RUN_TIMEOUT_SECONDS", raising=False)
    assert _run_timeout_seconds() == 0

    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "900")
    assert _run_timeout_seconds() == 900

    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "-5")
    assert _run_timeout_seconds() == 0

    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "abc")
    assert _run_timeout_seconds() == 0


def test_stream_frames_archives_failed_on_timeout(monkeypatch):
    from server.routers import sessions as S

    calls = _patch_settlement(monkeypatch)

    frames = asyncio.run(
        _collect(
            S._stream_frames(
                graph=_SlowGraph(),
                inputs={},
                config={},
                session_id="s1",
                user_id="u1",
                run_timeout=0.05,
                lock=None,
            )
        )
    )

    assert [_parse_frame(f)[0] for f in frames] == ["error"]
    assert "timed out" in _parse_frame(frames[0])[1]["message"]
    assert [c["status"] for c in calls] == ["failed"]
    assert "timed out" in calls[0]["error_message"]


def test_run_stream_rejects_a_user_over_quota(monkeypatch):
    from fastapi.testclient import TestClient

    from server import deps

    app, calls = _sessions_app(monkeypatch)

    async def fake_used(user_id: str) -> int:
        return 10**9

    monkeypatch.setattr(deps, "_tokens_used_today", fake_used)
    monkeypatch.setenv("MAX_TOKENS_PER_USER_PER_DAY", "1000")

    with TestClient(app) as client:
        res = client.post("/api/sessions/quota-session/runs/stream", json={})

    assert res.status_code == 429
    # Nothing was archived or locked: the request never started a run.
    assert calls == []


def test_done_frame_carries_usage_totals(monkeypatch):
    from server.routers import sessions as S

    _patch_settlement(monkeypatch)

    async def drive():
        gen = S._stream_frames(
            graph=_FakeGraph(
                items=[((), "updates", {"final_report_generation": {"final_report": "R"}})]
            ),
            inputs={},
            config={},
            session_id="s1",
            user_id="u1",
            run_timeout=0,
            lock=None,
        )
        return await _collect(gen)

    frames = asyncio.run(drive())
    done = _parse_frame(frames[-1])[1]

    assert done["status"] == "completed"
    assert done["usage"] == {}
