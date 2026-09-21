"""Graph manager: compiles the deep researcher graph with a Postgres checkpointer.

The core package compiles `deep_researcher` without a checkpointer at import
time (src/open_deep_research/deep_researcher.py:719). We deliberately do not
touch that module — instead we recompile from the exported
`deep_researcher_builder` with an AsyncPostgresSaver so thread state
(messages, brief, notes, final report) survives server restarts.
"""

import logging
from types import TracebackType

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from open_deep_research.deep_researcher import deep_researcher_builder
from server.db import checkpointer_dsn

logger = logging.getLogger(__name__)


def _redact(dsn: str) -> str:
    """Return the host/database part of a DSN, never the credentials."""
    return dsn.rsplit("@", 1)[-1]


class GraphManager:
    """Owns the checkpointer lifetime and the compiled graph singleton."""

    def __init__(self) -> None:
        """Leave the manager unstarted; call start() from the app lifespan."""
        self._cm = None
        self.graph = None

    async def start(self) -> bool:
        """Open the Postgres checkpointer and compile the graph.

        Returns True on success; False when DATABASE_URL is missing or the
        checkpointer cannot be opened (the server still boots so the UI and
        /api/health work in degraded mode).
        """
        dsn = checkpointer_dsn()
        if not dsn:
            logger.warning(
                "DATABASE_URL is not set; research runs will be unavailable "
                "(no checkpointer). Start PostgreSQL and restart the server."
            )
            return False

        try:
            self._cm = AsyncPostgresSaver.from_conn_string(dsn)
            checkpointer = await self._cm.__aenter__()
            await checkpointer.setup()  # idempotent: creates checkpoint tables
        except Exception:
            logger.exception(
                "Checkpointer could not connect to %s. On Windows psycopg's async "
                "mode refuses the ProactorEventLoop (start with "
                "`uv run python -m server`) and needs an IPv4 host: `localhost` can "
                "resolve to ::1 while Docker publishes 127.0.0.1 only.",
                _redact(dsn),
            )
            await self.stop()
            return False

        self.graph = deep_researcher_builder.compile(checkpointer=checkpointer)
        logger.info(
            "Deep researcher graph compiled with Postgres checkpointer (%s)",
            _redact(dsn),
        )
        return True

    async def stop(self) -> None:
        """Close the checkpointer connection (safe to call when unstarted)."""
        if self._cm is not None:
            exit_cm = self._cm
            self._cm = None
            self.graph = None
            try:
                # __aexit__ expects (exc_type, exc, tb)
                await exit_cm.__aexit__(None, None, None)
            except Exception:
                logger.warning("Error while closing the checkpointer", exc_info=True)

    def get_graph(self):
        """Return the compiled graph, raising a helpful error when unstarted."""
        if self.graph is None:
            raise RuntimeError(
                "Graph unavailable: DATABASE_URL is not configured or startup failed"
            )
        return self.graph

    async def __aenter__(self) -> "GraphManager":
        """Async context manager entry: start the graph."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Async context manager exit: stop the graph."""
        await self.stop()


manager = GraphManager()
