"""Authentication dependency for the custom FastAPI routes.

Two modes via AUTH_MODE:
- "local": no auth (returns a fixed dev user). Intended only for development.
- "supabase": verifies a Supabase JWT the same way src/security/auth.py does
  (Supabase client + get_user in a worker thread) and returns the user id.

Default: "supabase" when SUPABASE_URL/KEY are configured, otherwise "local"
so a fresh clone can run without a Supabase project.
"""

import asyncio
import logging
import os

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

LOCAL_DEV_USER = "local-dev-user"

# Supabase client, initialized with the same env vars as src/security/auth.py
# (duplicated here on purpose: `security` is not an installed package, and the
# auth middleware there is LangGraph-specific, not reusable as a FastAPI dep).
_supabase_client = None


def _get_supabase():
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if url and key:
            _supabase_client = create_client(url, key)
    return _supabase_client


def auth_mode() -> str:
    """Resolve the effective auth mode (explicit AUTH_MODE wins, else default)."""
    explicit = os.environ.get("AUTH_MODE")
    if explicit in ("local", "supabase"):
        return explicit
    return "supabase" if os.environ.get("SUPABASE_URL") else "local"


async def _verify_supabase_token(token: str) -> str | None:
    client = _get_supabase()
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="AUTH_MODE=supabase but SUPABASE_URL/SUPABASE_KEY are not configured",
        )
    try:
        user = await asyncio.to_thread(client.auth.get_user, token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if user is None or not getattr(user, "user", None):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return str(user.user.id)


def apply_cost_caps(configurable: dict) -> dict:
    """Clamp research spend knobs when running without auth (dev mode).

    A single deep research run can cost dollars; unauthenticated local
    servers must not be able to trigger unbounded runs.
    """
    caps = {"max_concurrent_research_units": 1, "max_researcher_iterations": 2}
    out = dict(configurable)
    for key, cap in caps.items():
        value = out.get(key, cap)
        try:
            out[key] = min(int(value), cap)
        except (TypeError, ValueError):
            out[key] = cap
    return out


async def get_current_user_id(
    authorization: str | None = Header(default=None),
) -> str:
    """FastAPI dependency: current user id from the Supabase JWT (or local dev)."""
    mode = auth_mode()
    if mode == "local":
        logger.debug("AUTH_MODE=local: request accepted without authentication")
        return LOCAL_DEV_USER

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    user_id = await _verify_supabase_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id
