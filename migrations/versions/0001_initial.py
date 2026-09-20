"""Create the initial business schema (research_reports).

Revision ID: 0001
Revises:
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create research_reports and its user/time index."""
    op.create_table(
        "research_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("research_brief", sa.Text(), nullable=True),
        sa.Column("final_report", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_reports_user_created",
        "research_reports",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    """Drop the research_reports table."""
    op.drop_index("idx_reports_user_created", table_name="research_reports")
    op.drop_table("research_reports")
