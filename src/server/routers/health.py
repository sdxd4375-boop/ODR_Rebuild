"""Health endpoint: reports which subsystems are available."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from server.deps import auth_mode

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    """Liveness plus readiness; 503 when a required subsystem is unavailable."""
    db_ready = bool(getattr(request.app.state, "db_ready", False))
    graph_ready = bool(getattr(request.app.state, "graph_ready", False))
    ok = db_ready and graph_ready
    return JSONResponse(
        {
            "status": "ok" if ok else "degraded",
            "db": db_ready,
            "graph": graph_ready,
            "auth_mode": auth_mode(),
            "detail": ""
            if ok
            else "database or graph unavailable - check DATABASE_URL and startup logs",
        },
        status_code=200 if ok else 503,
    )