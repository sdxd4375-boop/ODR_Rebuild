"""Health endpoint: reports which subsystems are available."""

from fastapi import APIRouter, Request

from server.deps import auth_mode

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    """Liveness plus readiness of the database, graph, and auth subsystems."""
    return {
        "status": "ok",
        "db": bool(getattr(request.app.state, "db_ready", False)),
        "graph": bool(getattr(request.app.state, "graph_ready", False)),
        "auth_mode": auth_mode(),
    }
