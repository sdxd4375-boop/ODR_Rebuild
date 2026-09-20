"""Custom HTTP interfaces for Open Deep Research.

A self-hosted FastAPI application that invokes the core research graph
directly (with a Postgres checkpointer for session persistence) and serves
the web frontend. Run with:

    uv run uvicorn server.app:app --app-dir src --port 8000
"""
