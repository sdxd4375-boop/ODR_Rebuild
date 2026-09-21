"""FastAPI application: sessions API + health + optional static frontend."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from server import db, deps, graphs
from server.deps import auth_mode
from server.routers import documents, export, health, sessions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB + graph on startup; record readiness flags for /api/health."""
    deps.ensure_env_loaded()

    app.state.db_ready = await db.init_engine()
    app.state.graph_ready = await graphs.manager.start()
    logger.info(
        "Startup complete (db=%s, graph=%s, auth_mode=%s)",
        app.state.db_ready,
        app.state.graph_ready,
        auth_mode(),
    )
    yield
    await graphs.manager.stop()
    await db.close_engine()


app = FastAPI(title="Open Deep Research API", version="0.1.0", lifespan=lifespan)

app.include_router(health.router, prefix="/api")
app.include_router(sessions.router, prefix="/api/sessions")
app.include_router(documents.router, prefix="/api/documents")
app.include_router(export.router, prefix="/api/sessions")

# Serve the built frontend (production). Build with: cd web && npm run build
_web_dist = os.environ.get("WEB_DIST", "web/dist")
if os.path.isdir(_web_dist):
    app.mount("/", StaticFiles(directory=_web_dist, html=True), name="web")
