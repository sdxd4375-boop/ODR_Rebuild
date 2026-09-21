"""Windows-safe server launcher: ``uv run python -m server``.

psycopg's async mode refuses Python's default Windows ProactorEventLoop, and
uvicorn creates that loop before it imports the app — so the LangGraph
checkpointer cannot connect when starting with ``uvicorn server.app:app``.
Selecting the Selector event loop policy *before* uvicorn starts avoids it.

Environment: ODR_HOST (default 127.0.0.1), ODR_PORT (default 8000).
"""

import asyncio
import os
import sys


def main() -> None:
    """Run the API with a psycopg-compatible event loop on Windows."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    import uvicorn

    uvicorn.run(
        "server.app:app",
        host=os.environ.get("ODR_HOST", "127.0.0.1"),
        port=int(os.environ.get("ODR_PORT", "8000")),
    )


if __name__ == "__main__":
    main()