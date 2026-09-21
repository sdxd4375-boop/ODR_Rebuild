"""Windows-friendly dev launcher for the FastAPI server.

`uv run uvicorn ...` can be blocked on Windows by Smart App Control / WDAC
(os error 4551) because it needs to execute an unsigned temporary exe; running
uvicorn from a real Python interpreter avoids that. This also selects the
Selector event loop policy, which asyncpg/psycopg need on Windows (the default
ProactorEventLoop can break the Postgres checkpointer).

Usage: uv run python scripts/dev_server.py
"""

import asyncio
import sys

import uvicorn


def main() -> None:
    """Run the API on 127.0.0.1:8000 with a Windows-compatible event loop."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run("server.app:app", app_dir="src", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()