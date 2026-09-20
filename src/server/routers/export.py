"""Report export + chart generation endpoints."""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from server import exporters
from server.deps import get_current_user_id
from server.models import ResearchReport
from server.routers.sessions import _get_session, _session_factory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["export"])


def _charts_dir(session_id: str) -> str:
    """Session chart directory.

    Layout: data/charts/{session_id}/charts/<file>.png — this keeps the
    report's `charts/<file>` references resolvable from the session data
    root (used as base_dir by the exporters).
    """
    path = os.path.join(os.environ.get("ODR_CHARTS_DIR", "data/charts"), session_id, "charts")
    os.makedirs(path, exist_ok=True)
    return path


def _report_dir(session_id: str) -> str:
    path = os.path.join("data", "exports", session_id)
    os.makedirs(path, exist_ok=True)
    return path


@router.post("/{session_id}/charts")
async def generate_session_charts(
    session_id: str, user_id: str = Depends(get_current_user_id)
):
    """Generate sandboxed matplotlib charts from the archived final report."""
    row = await _get_session(user_id, session_id)
    if not row.final_report:
        raise HTTPException(status_code=400, detail="Session has no final report to chart")

    from server.charts import generate_charts

    updated, saved = generate_charts(row.final_report, _charts_dir(session_id))
    if saved:
        factory = _session_factory()
        async with factory() as db:
            db_row = await db.get(ResearchReport, session_id)
            db_row.final_report = updated
            await db.commit()
    return {"charts": [os.path.basename(p) for p in saved]}


@router.get("/{session_id}/export/{fmt}")
async def export_session_report(
    session_id: str, fmt: str, user_id: str = Depends(get_current_user_id)
):
    """Export the final report as PPTX or DOCX (charts embedded when present)."""
    if fmt not in exporters.EXPORTERS:
        raise HTTPException(status_code=400, detail=f"Unsupported format '{fmt}'")
    row = await _get_session(user_id, session_id)
    if not row.final_report:
        raise HTTPException(status_code=400, detail="Session has no final report to export")

    out_path = os.path.join(_report_dir(session_id), f"report.{fmt}")
    base_dir = os.path.dirname(_charts_dir(session_id))  # session data root
    try:
        exporters.EXPORTERS[fmt](row.final_report, out_path, base_dir=base_dir)
    except Exception as exc:  # noqa: BLE001 — conversion errors
        logger.exception("Export to %s failed for session %s", fmt, session_id)
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}")

    media = {
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }[fmt]
    return FileResponse(
        out_path,
        media_type=media,
        filename=f"{session_id}.{fmt}",
    )
