"""Lightweight local document index for RAG (no external vector DB required).

Chunks are embedded and kept in a JSON file under ODR_DOCS_DIR (default
./data/docs). Retrieval is cosine similarity over numpy vectors — entirely
adequate for personal-scale document sets (hundreds of pages) and zero extra
infrastructure. The embed function is injectable so tests run offline; the
production default embeds with the configured OpenAI-compatible endpoint.
"""

import asyncio
import hashlib
import json
import logging
import os
import threading
from typing import Any, Callable

import numpy as np

logger = logging.getLogger(__name__)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

EmbedFn = Callable[[list[str]], list[list[float]]]


def default_embed_fn(texts: list[str]) -> list[list[float]]:
    """Embed texts with the configured provider (env EMBEDDING_MODEL).

    Kept lazy so importing this module never requires API access.
    """
    model = os.environ.get("EMBEDDING_MODEL", "openai:text-embedding-3-small")
    provider, _, model_name = model.partition(":")
    if provider != "openai":
        raise ValueError(f"Unsupported embedding provider: {provider}")
    from langchain_openai import OpenAIEmbeddings

    embeddings = OpenAIEmbeddings(model=model_name)
    return embeddings.embed_documents(texts)


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Sliding-window chunking; page separators (form feed) start new chunks."""
    chunks: list[str] = []
    for page in text.split("\f"):
        page = page.strip()
        if not page:
            continue
        start = 0
        while start < len(page):
            chunks.append(page[start : start + size])
            start += size - overlap
    return [c for c in chunks if c.strip()]


class LocalDocIndex:
    """Persistent chunk store with cosine-similarity retrieval."""

    def __init__(self, index_dir: str, embed_fn: EmbedFn | None = None) -> None:
        """Bind the index to a directory and an embedding function."""
        self.index_dir = index_dir
        self.embed_fn = embed_fn or default_embed_fn
        self.index_file = os.path.join(index_dir, "docs_index.json")
        self._lock = threading.Lock()
        self.docs: dict[str, dict[str, Any]] = {}  # doc_id -> {title, pages}
        self.chunks: list[dict[str, Any]] = []  # {doc_id, title, page, text, embedding}
        self._load()

    # ------------------------------------------------ persistence
    def _load(self) -> None:
        if not os.path.exists(self.index_file):
            return
        try:
            with open(self.index_file, encoding="utf-8") as f:
                payload = json.load(f)
            self.docs = payload.get("docs", {})
            self.chunks = payload.get("chunks", [])
        except Exception:  # noqa: BLE001 — corrupt index treated as empty
            logger.exception("Failed to load doc index at %s", self.index_file)

    def _save(self) -> None:
        os.makedirs(self.index_dir, exist_ok=True)
        tmp = self.index_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"docs": self.docs, "chunks": self.chunks}, f, ensure_ascii=False)
        os.replace(tmp, self.index_file)

    # ------------------------------------------------ operations
    def add_document(
        self, title: str, text: str, doc_id: str | None = None
    ) -> dict[str, Any]:
        """Chunk, embed and persist one document. Returns its metadata."""
        doc_id = doc_id or hashlib.md5(title.encode()).hexdigest()[:12]
        pages = text.split("\f")
        pieces = chunk_text(text)

        # Track which page each chunk came from by walking the page offsets.
        page_of: list[int] = []
        cursor = 0
        for page_no, page in enumerate(pages, start=1):
            while cursor < len(pieces) and page.find(pieces[cursor][:40]) >= 0:
                page_of.append(page_no)
                cursor += 1
        page_of += [1] * (len(pieces) - len(page_of))

        vectors = self.embed_fn(pieces)
        with self._lock:
            self.chunks = [c for c in self.chunks if c["doc_id"] != doc_id]
            for piece, vec, page_no in zip(pieces, vectors, page_of):
                self.chunks.append(
                    {
                        "doc_id": doc_id,
                        "title": title,
                        "page": page_no,
                        "text": piece,
                        "embedding": [round(v, 6) for v in vec],
                    }
                )
            self.docs[doc_id] = {"title": title, "chunks": len(pieces)}
            self._save()
        return {"doc_id": doc_id, "title": title, "chunks": len(pieces)}

    def remove_document(self, doc_id: str) -> bool:
        """Delete a document and its chunks; False when the id is unknown."""
        with self._lock:
            if doc_id not in self.docs:
                return False
            del self.docs[doc_id]
            self.chunks = [c for c in self.chunks if c["doc_id"] != doc_id]
            self._save()
        return True

    async def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Top-k passages by cosine similarity (async for tool-call symmetry)."""
        if not self.chunks:
            return []
        [query_vec] = await asyncio.to_thread(self.embed_fn, [query])
        q = np.asarray(query_vec, dtype=np.float32)
        matrix = np.asarray([c["embedding"] for c in self.chunks], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(q) or 1.0)
        norms[norms == 0] = 1e-9
        scores = matrix @ q / norms
        top = np.argsort(scores)[::-1][:k]
        return [self.chunks[i] | {"score": float(scores[i])} for i in top]


_index: LocalDocIndex | None = None


def get_doc_index() -> LocalDocIndex:
    """Process-wide index bound to ODR_DOCS_DIR (default ./data/docs)."""
    global _index
    if _index is None:
        _index = LocalDocIndex(os.environ.get("ODR_DOCS_DIR", os.path.join("data", "docs")))
    return _index
