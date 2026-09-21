"""Sessions API: create/list research sessions and stream a run over SSE.

Session id == LangGraph thread_id. Thread state (messages, brief, notes,
final report) lives in the Postgres checkpointer; this router also archives
the final report into the `research_reports` business table so the frontend
can list history without reading checkpoint internals.
"""

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from server import graphs
from server.db import get_session_factory
from server.deps import (
    apply_cost_caps,
    auth_mode,
    enforce_token_quota,
    get_current_user_id,
)
from server.models import ResearchReport, UsageEvent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sessions"])

# Status transitions: created -> running -> awaiting_input | completed | failed | cancelled
# `finished_at` is stamped for every terminal status.
TERMINAL_STATUSES = frozenset({"awaiting_input", "completed", "failed", "cancelled"})

# One in-flight run per session. NOTE: process-local — it only holds for a single
# worker. Running multiple workers (`uvicorn --workers N`) would need a Postgres
# advisory lock (`pg_try_advisory_lock(hashtext(thread_id))`) instead.
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(thread_id: str) -> asyncio.Lock:
    """Per-thread mutex: at most one in-flight run per session."""
    return _locks.setdefault(thread_id, asyncio.Lock())


def _run_timeout_seconds() -> int:
    """Wall-clock cap for one run, in seconds (``RUN_TIMEOUT_SECONDS``).

    0 — the default — means unlimited, so behaviour is unchanged until an
    operator opts in.
    """
    raw = os.environ.get("RUN_TIMEOUT_SECONDS", "") or 0
    try:
        return max(int(float(raw)), 0)
    except (TypeError, ValueError):
        return 0


class CreateSessionRequest(BaseModel):
    """Body of POST /api/sessions."""

    question: str = Field(min_length=1, description="The initial research question")


class RunRequest(BaseModel):
    """Body of POST /api/sessions/{id}/runs/stream."""

    message: str | None = Field(
        default=None,
        description="Follow-up user message (e.g. answering a clarification). "
        "Omitted on the first run: the stored question is used.",
    )
    configurable: dict[str, Any] = Field(default_factory=dict)


class SessionOut(BaseModel):
    """Serialized research session as returned by the API."""

    id: str
    question: str
    status: str
    research_brief: str | None = None
    final_report: str | None = None
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


def _sse(event: str, data: Any) -> str:
    """Format one Server-Sent Events frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _extract_text(content: Any) -> str:
    """Flatten LangChain message content (str or content blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content) if content else ""


def aggregate_usage(usage_acc: dict[tuple[str, str], dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Reduce per-call token records to per-node totals.

    `usage_acc` keeps the LAST usage_metadata seen per (node, message_id):
    providers stream either a single final usage chunk (OpenAI) or cumulative
    usage (Anthropic) — in both cases the last value is the call total, so
    summing the per-call totals avoids double counting.
    """
    aggregated: dict[str, dict[str, Any]] = {}
    for (node, _msg_id), u in usage_acc.items():
        bucket = aggregated.setdefault(
            node, {"input": 0, "output": 0, "total": 0, "calls": 0, "model": u.get("model")}
        )
        bucket["input"] += int(u.get("input") or 0)
        bucket["output"] += int(u.get("output") or 0)
        bucket["total"] += int(u.get("total") or 0)
        bucket["calls"] += 1
    return aggregated


def _map_stream_item(
    ns: tuple[str, ...] | list[str] | None,
    mode: str,
    payload: Any,
    usage_acc: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[tuple[str, dict[str, Any]]], str | None]:
    """Translate one ``astream(subgraphs=True)`` item into SSE frames.

    Returns the frames to emit plus a final report when this item produced one.
    Subgraph items (non-empty namespace) are tagged with ``subgraph: True`` and
    their ``namespace`` so the client can tell ``researcher`` apart from a
    same-named root node; before this, every subgraph event was dropped.

    ``usage_acc`` is mutated in place and keyed by (node, message id): providers
    stream either one final usage chunk or cumulative usage, so the last chunk
    for an id wins (see ``aggregate_usage``).
    """
    frames: list[tuple[str, dict[str, Any]]] = []
    final_report: str | None = None

    namespace = tuple(ns or ())
    subgraph = bool(namespace)
    namespace_label = "/".join(namespace)

    if mode == "updates":
        for node, update in (payload or {}).items():
            data: dict[str, Any] = {"node": node, "subgraph": subgraph}
            if subgraph:
                data["namespace"] = namespace_label
            frames.append(("node", data))
            if node == "final_report_generation":
                final_report = (update or {}).get("final_report") or None
        return frames, final_report

    # mode == "messages": payload is (chunk, metadata)
    chunk, metadata = payload
    node = (metadata or {}).get("langgraph_node", "")
    usage_metadata = getattr(chunk, "usage_metadata", None)
    chunk_id = getattr(chunk, "id", None)
    if usage_metadata and chunk_id:
        input_tokens = usage_metadata.get("input_tokens") or 0
        output_tokens = usage_metadata.get("output_tokens") or 0
        if not output_tokens:
            # Some providers report only input+total, and langchain normalises a
            # missing output_tokens to 0 — derive it from the difference instead
            # of silently recording zero output.
            output_tokens = max((usage_metadata.get("total_tokens") or 0) - input_tokens, 0)
        total_tokens = usage_metadata.get("total_tokens") or (input_tokens + output_tokens)
        usage_acc[(node, chunk_id)] = {
            "input": input_tokens,
            "output": output_tokens,
            "total": total_tokens,
            "model": (getattr(chunk, "response_metadata", {}) or {}).get("model_name"),
        }

    content = _extract_text(getattr(chunk, "content", ""))
    if content:
        data = {"node": node, "content": content, "subgraph": subgraph}
        if subgraph:
            data["namespace"] = namespace_label
        frames.append(("message", data))
    return frames, None


async def _record_usage(user_id: str, thread_id: str, aggregated: dict[str, dict[str, Any]]) -> None:
    """Persist one UsageEvent row per node; best-effort (never fail the run)."""
    if not aggregated:
        return
    try:
        factory = _session_factory()
        async with factory() as db:
            for node, u in aggregated.items():
                db.add(
                    UsageEvent(
                        user_id=user_id,
                        thread_id=thread_id,
                        node=node[:64],
                        model=u.get("model"),
                        input_tokens=u["input"],
                        output_tokens=u["output"],
                        total_tokens=u["total"],
                        call_count=u["calls"],
                    )
                )
            await db.commit()
    except Exception:  # noqa: BLE001 — metering must not break the run
        logger.warning("Failed to record usage for thread %s", thread_id, exc_info=True)


def _session_factory():
    """Session factory or a clean 503 when the database is not configured."""
    try:
        return get_session_factory()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {exc} (set DATABASE_URL and restart)",
        )


async def _get_session(user_id: str, session_id: str) -> ResearchReport:
    factory = _session_factory()
    async with factory() as db:
        row = await db.get(ResearchReport, session_id)
        if row is None or row.user_id != user_id:
            raise HTTPException(status_code=404, detail="Session not found")
        return row


async def _archive(
    session_id: str,
    *,
    status: str,
    research_brief: str | None = None,
    final_report: str | None = None,
    error_message: str | None = None,
) -> None:
    factory = _session_factory()
    async with factory() as db:
        row = await db.get(ResearchReport, session_id)
        if row is None:
            return
        row.status = status
        if research_brief is not None:
            row.research_brief = research_brief
        if final_report is not None:
            row.final_report = final_report
        if error_message is not None:
            row.error_message = error_message
        if status in TERMINAL_STATUSES:
            row.finished_at = datetime.now(UTC)
        await db.commit()


async def _settle_run(
    session_id: str,
    user_id: str,
    *,
    usage_acc: dict[tuple[str, str], dict[str, Any]],
    status: str,
    final_report: str | None = None,
    research_brief: str | None = None,
    error_message: str | None = None,
) -> None:
    """Persist usage plus the terminal status, surviving task cancellation.

    A client disconnect reaches the streaming generator as ``GeneratorExit``
    (or ``CancelledError`` when the surrounding task is cancelled). Awaiting the
    write directly can be re-cancelled by the outer cancel scope, which left
    sessions stuck in "running" forever; the write therefore runs in its own
    task and we only wait on a shield.
    """

    async def _write() -> None:
        await _record_usage(user_id, session_id, aggregate_usage(usage_acc))
        await _archive(
            session_id,
            status=status,
            research_brief=research_brief,
            final_report=final_report,
            error_message=error_message,
        )

    task = asyncio.create_task(_write())
    try:
        await asyncio.shield(task)
    except BaseException:  # noqa: BLE001 — cancellation must not lose the archive
        logger.info(
            "Settlement for session %s continues in the background (status=%s)",
            session_id,
            status,
        )


async def _stream_frames(
    *,
    graph: Any,
    inputs: dict[str, Any],
    config: dict[str, Any],
    session_id: str,
    user_id: str,
    run_timeout: int = 0,
    lock: asyncio.Lock | None = None,
):
    """Yield the SSE frames of one run, always leaving a terminal status behind.

    Extracted from the endpoint so the settlement contract (completed / failed /
    cancelled) can be driven directly in offline tests.
    """
    final_report: str | None = None
    usage_acc: dict[tuple[str, str], dict[str, Any]] = {}
    settled = False
    try:
        try:
            async with asyncio.timeout(run_timeout or None):
                async for ns, mode, payload in graph.astream(
                    inputs,
                    config,
                    stream_mode=["updates", "messages"],
                    subgraphs=True,
                ):
                    frames, report = _map_stream_item(ns, mode, payload, usage_acc)
                    if report:
                        final_report = report
                    for event, data in frames:
                        yield _sse(event, data)
        except TimeoutError:
            message = f"run timed out after {run_timeout}s"
            logger.warning("Run timed out for session %s (%s)", session_id, message)
            await _settle_run(
                session_id,
                user_id,
                usage_acc=usage_acc,
                status="failed",
                final_report=final_report,
                error_message=message,
            )
            settled = True
            yield _sse("error", {"message": message})
            return

        # Classify the outcome from the persisted thread state.
        brief: str | None = None
        status = "completed"
        if not final_report:
            snapshot = await graph.aget_state(config)
            values = snapshot.values or {}
            brief = values.get("research_brief")
            last = (values.get("messages") or [None])[-1]
            if isinstance(last, AIMessage):
                # clarify_with_user ended the run without a report
                status = "awaiting_input"
            else:
                status = "failed"
                final_report = None

        await _settle_run(
            session_id,
            user_id,
            usage_acc=usage_acc,
            status=status,
            research_brief=brief,
            final_report=final_report,
        )
        settled = True
        yield _sse(
            "done",
            {
                "status": status,
                "final_report": final_report,
                "usage": aggregate_usage(usage_acc),
            },
        )
    except Exception as exc:  # noqa: BLE001 — surfaced to the client
        logger.exception("Run failed for session %s", session_id)
        await _settle_run(
            session_id,
            user_id,
            usage_acc=usage_acc,
            status="failed",
            final_report=final_report,
            error_message=str(exc),
        )
        settled = True
        yield _sse("error", {"message": str(exc)})
    except BaseException:
        # Client disconnected or the task was cancelled: no frame can be
        # delivered any more, but the session must not stay "running".
        logger.info("Run cancelled for session %s", session_id)
        if not settled:
            await _settle_run(
                session_id,
                user_id,
                usage_acc=usage_acc,
                status="cancelled",
                final_report=final_report,
            )
    finally:
        if lock is not None and lock.locked():
            lock.release()


@router.post("", response_model=SessionOut)
async def create_session(
    body: CreateSessionRequest, user_id: str = Depends(get_current_user_id)
):
    """Register a new research session (status=created, no run started yet)."""
    row = ResearchReport(user_id=user_id, question=body.question, status="created")
    factory = _session_factory()
    async with factory() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return SessionOut(
        id=row.id,
        question=row.question,
        status=row.status,
        created_at=row.created_at,
    )


@router.get("")
async def list_sessions(
    user_id: str = Depends(get_current_user_id),
    limit: int = 20,
    offset: int = 0,
):
    """List the current user's sessions, newest first."""
    limit = max(1, min(limit, 100))
    factory = _session_factory()
    async with factory() as db:
        base = (
            select(ResearchReport)
            .where(ResearchReport.user_id == user_id)
            .order_by(desc(ResearchReport.created_at))
        )
        rows = (await db.scalars(base.limit(limit).offset(offset))).all()
        total = await db.scalar(
            select(func.count(ResearchReport.id)).where(
                ResearchReport.user_id == user_id
            )
        )
    items = [
        SessionOut(
            id=r.id,
            question=r.question,
            status=r.status,
            research_brief=r.research_brief,
            final_report=r.final_report,
            error_message=r.error_message,
            created_at=r.created_at,
            finished_at=r.finished_at,
        ).model_dump(mode="json")
        for r in rows
    ]
    return {"items": items, "total": total or 0}


@router.get("/{session_id}")
async def get_session(
    session_id: str, user_id: str = Depends(get_current_user_id)
):
    """Session detail: archived fields plus live thread state (messages)."""
    row = await _get_session(user_id, session_id)

    # Live thread state from the checkpointer (source of truth for messages).
    messages = []
    final_report = row.final_report
    if graphs.manager.graph is not None:
        try:
            snapshot = await graphs.manager.graph.aget_state(
                {"configurable": {"thread_id": session_id}}
            )
            values = snapshot.values or {}
            final_report = values.get("final_report") or final_report
            for msg in values.get("messages", []):
                role = "assistant" if isinstance(msg, AIMessage) else "user"
                messages.append({"role": role, "content": _extract_text(msg.content)})
        except Exception as exc:
            logger.warning("Could not read thread state for %s: %s", session_id, exc)

    return {
        "id": row.id,
        "question": row.question,
        "status": row.status,
        "research_brief": row.research_brief,
        "final_report": final_report,
        "error_message": row.error_message,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
        "messages": messages,
    }


@router.post("/{session_id}/runs/stream")
async def stream_run(
    session_id: str,
    body: RunRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Run the research graph for a session and stream progress over SSE.

    Emits `node` events (a graph node finished), `message` events (streamed
    LLM text tagged with its node), and a final `done` or `error` event. On
    completion the outcome is archived into the research_reports table.
    """
    row = await _get_session(user_id, session_id)
    await enforce_token_quota(user_id)
    graph = graphs.manager.get_graph()

    message = body.message or row.question
    if not message:
        raise HTTPException(status_code=400, detail="No question or message provided")

    configurable = dict(body.configurable)
    if auth_mode() == "local":
        configurable = apply_cost_caps(configurable)

    config = {"configurable": {**configurable, "thread_id": session_id}}
    inputs = {"messages": [{"role": "user", "content": message}]}

    # Reject a second concurrent run on the same thread: two overlapping
    # `astream` calls would race on the same checkpointer state. The
    # locked()/acquire() pair is atomic here because nothing awaits between them.
    lock = _lock_for(session_id)
    if lock.locked():
        raise HTTPException(
            status_code=409, detail="This session already has a run in progress"
        )
    await lock.acquire()
    try:
        await _archive(session_id, status="running")
    except BaseException:
        lock.release()
        raise

    return StreamingResponse(
        _stream_frames(
            graph=graph,
            inputs=inputs,
            config=config,
            session_id=session_id,
            user_id=user_id,
            run_timeout=_run_timeout_seconds(),
            lock=lock,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
