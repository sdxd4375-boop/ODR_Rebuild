"""Pluggable retrievers extending the researcher's search toolkit.

Loaded through the `extra_retrievers` configuration field (comma-separated
names, e.g. "duckduckgo,arxiv,local_docs"). The only core-code touch is one
`tools.extend(...)` line in utils.get_all_tools — every engine lives here or
in the server layer, keeping the research graph untouched.

Web engines are adapted from src/legacy/utils.py (the pre-0.0.x multi-engine
implementation), reformatted to the same "--- SOURCE N ---" convention the
research prompts already expect (see utils.tavily_search).
"""

import asyncio
import logging
import os
import random
import time
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

MAX_CHARS_PER_SOURCE = 4000


def format_sources(results: list[dict[str, Any]], source_label: str) -> str:
    """Format search results into the standard source block used by prompts."""
    lines = []
    for i, r in enumerate(results, start=1):
        lines.append(f"--- SOURCE {i}: {r.get('title', '')} [{source_label}] ---")
        lines.append(f"URL: {r.get('url', '')}")
        content = (r.get("content") or "")[:MAX_CHARS_PER_SOURCE]
        lines.append(f"SUMMARY: {content}")
        lines.append("")
    return "\n".join(lines).strip()


async def _run_in_thread(fn, *args):
    return await asyncio.to_thread(fn, *args)


##########################
# DuckDuckGo (no API key)
##########################

def _duckduckgo_sync(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    from duckduckgo_search import DDGS

    max_retries, backoff = 3, 2.0
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            q = query
            if attempt > 0:
                time.sleep(backoff**attempt + random.random())
                q = f"{query} {random.choice(['about', 'info', 'guide', 'overview'])}"
            with DDGS() as ddgs:
                rows = list(ddgs.text(q, max_results=max_results))
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "content": r.get("body", ""),
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001 — retried below
            last_exc = exc
    raise RuntimeError(f"DuckDuckGo search failed after retries: {last_exc}")


@tool
async def duckduckgo_web_search(query: str) -> str:
    """Search the public web with DuckDuckGo (no API key required).

    Use for general web research when Tavily is unavailable or for
    cross-checking. Returns a list of titled sources with URLs and snippets.
    """
    try:
        results = await _run_in_thread(_duckduckgo_sync, query)
    except Exception as exc:  # noqa: BLE001 — surfaced to the model
        return f"Error searching DuckDuckGo: {exc}"
    if not results:
        return "No results found."
    return format_sources(results, "DuckDuckGo")


##########################
# arXiv (academic papers)
##########################

def _arxiv_sync(query: str, load_max_docs: int = 5) -> list[dict[str, Any]]:
    from langchain_community.retrievers import ArxivRetriever

    retriever = ArxivRetriever(
        load_max_docs=load_max_docs,
        get_full_documents=False,
        load_all_available_meta=True,
    )
    docs = retriever.invoke(query)
    results = []
    for doc in docs:
        meta = doc.metadata
        parts = []
        if meta.get("Summary"):
            parts.append(f"Summary: {meta['Summary']}")
        if meta.get("Authors"):
            parts.append(f"Authors: {meta['Authors']}")
        published = meta.get("Published")
        if published:
            published = published.isoformat() if hasattr(published, "isoformat") else str(published)
            parts.append(f"Published: {published}")
        results.append(
            {
                "title": meta.get("Title", ""),
                "url": meta.get("entry_id", ""),
                "content": "\n".join(parts) or (doc.page_content or "")[:MAX_CHARS_PER_SOURCE],
            }
        )
    return results


@tool
async def arxiv_search(query: str) -> str:
    """Search arXiv for academic papers (preprints in CS, physics, math, etc.).

    Returns paper titles, abstracts, authors, publication dates and arXiv URLs.
    Prefer this tool for scientific or technical literature questions.
    """
    try:
        results = await _run_in_thread(_arxiv_sync, query)
    except Exception as exc:  # noqa: BLE001 — surfaced to the model
        return f"Error searching arXiv: {exc}"
    if not results:
        return "No results found."
    return format_sources(results, "arXiv")


##########################
# Local documents (RAG)
##########################

@tool
async def local_docs_search(query: str) -> str:
    """Search the user's uploaded local documents (hybrid private-knowledge lookup).

    Returns the most relevant passages from ingested documents, each tagged
    with its document title and page. Use for questions that may relate to
    the user's own materials.
    """
    from open_deep_research.docstore import get_doc_index

    try:
        index = get_doc_index()
        if not index.chunks:
            return "No local documents have been ingested yet."
        hits = await index.search(query, k=5)
        if not hits:
            return "No matching passages in local documents."
        results = [
            {
                "title": f"{h['title']} (p.{h['page']})",
                "url": f"local://{h['doc_id']}#page={h['page']}",
                "content": h["text"],
            }
            for h in hits
        ]
    except Exception as exc:  # noqa: BLE001 — surfaced to the model
        return f"Error searching local documents: {exc}"
    return format_sources(results, "LocalDocs")


##########################
# Registry
##########################

RETRIEVER_TOOLS = {
    "duckduckgo": duckduckgo_web_search,
    "arxiv": arxiv_search,
    "local_docs": local_docs_search,
}


def parse_extra_retrievers(configurable: dict[str, Any]) -> list[str]:
    """Parse the comma-separated `extra_retrievers` setting into names."""
    raw = configurable.get("extra_retrievers")
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        names = list(raw)
    else:
        names = str(raw).split(",")
    return [n.strip().lower() for n in names if n.strip()]


async def load_extra_retrievers(config: RunnableConfig | None = None) -> list:
    """Resolve configured extra retriever tools, skipping unknown names.

    Never raises: a broken optional retriever must not take down the
    researcher's tool assembly.
    """
    configurable = (config or {}).get("configurable", {}) or {}
    names = parse_extra_retrievers(configurable)
    if not names:
        # Fall back to the environment (Configuration env-precedence quirk).
        env_val = os.environ.get("EXTRA_RETRIEVERS", "")
        names = [n.strip().lower() for n in env_val.split(",") if n.strip()]
    tools = []
    for name in names:
        tool_obj = RETRIEVER_TOOLS.get(name)
        if tool_obj is None:
            logger.warning("Unknown extra retriever '%s' — skipped", name)
            continue
        tools.append(tool_obj)
    return tools
