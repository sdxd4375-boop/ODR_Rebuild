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


class GraphManager:
    """Owns the checkpointer lifetime and the compiled graph singleton."""

    def __init__(self) -> None:
        """Leave the manager unstarted; call start() from the app lifespan."""
        self._cm = None
        self.graph = None

    async def start(self) -> bool:
        """Open the Postgres checkpointer and compile the graph.

        Returns True on success; False when DATABASE_URL is not configured
        (the server still boots so the UI/health endpoint work).
        """
        dsn = checkpointer_dsn()
        if not dsn:
            logger.warning(
                "DATABASE_URL is not set; research runs will be unavailable "
                "(no checkpointer). Start PostgreSQL and restart the server."
            )
            return False

        self._cm = AsyncPostgresSaver.from_conn_string(dsn)
        checkpointer = await self._cm.__aenter__()
        await checkpointer.setup()  # idempotent: creates checkpoint tables
        self.graph = deep_researcher_builder.compile(checkpointer=checkpointer)
        logger.info("Deep researcher graph compiled with Postgres checkpointer")
        return True

    async def stop(self) -> None:
        """Close the checkpointer connection (safe to call when unstarted)."""
        if self._cm is not None:
            exit_cm = self._cm
            self._cm = None
            self.graph = None
            # __aexit__ expects (exc_type, exc, tb)
            await exit_cm.__aexit__(None, None, None)

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
