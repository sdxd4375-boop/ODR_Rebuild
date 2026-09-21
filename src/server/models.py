"""ORM models for the business schema owned by src/server."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from server.db import Base


def new_thread_id() -> str:
    """Generate a fresh UUID usable as both row id and LangGraph thread_id."""
    return str(uuid.uuid4())


class ResearchReport(Base):
    """One research session: the user-facing archive of a deep research run.

    `id` doubles as the LangGraph thread_id, so checkpointer state (messages,
    research brief, notes...) and this row describe the same conversation.
    """

    __tablename__ = "research_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_thread_id)
    user_id: Mapped[str] = mapped_column(String(128))
    question: Mapped[str] = mapped_column(Text)
    research_brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    # created -> running -> awaiting_input | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), default="created")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("idx_reports_user_created", "user_id", "created_at"),)


class UsageEvent(Base):
    """Token usage per (session, graph node).

    The basis for cost attribution and future quotas; one row per node per run.
    """

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128))
    thread_id: Mapped[str] = mapped_column(String(36), index=True)
    node: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    total_tokens: Mapped[int] = mapped_column(default=0)
    call_count: Mapped[int] = mapped_column(default=0)
    # Reserved for future pricing; stored as integer cents to avoid float drift.
    cost_cents: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("idx_usage_user_created", "user_id", "created_at"),)
