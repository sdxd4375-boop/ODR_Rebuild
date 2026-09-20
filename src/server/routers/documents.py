"""Document ingestion API for local-docs RAG."""

import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from open_deep_research.docstore import get_doc_index
from server.deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md"}


def _extract_text(filename: str, payload: bytes) -> str:
    """Extract plain text; PDF pages separated by form feed (used by chunker)."""
    suffix = os.path.splitext(filename)[1].lower()
    if suffix == ".pdf":
        import pymupdf

        with pymupdf.open(stream=payload, filetype="pdf") as pdf:
            return "\f".join(page.get_text() for page in pdf)
    return payload.decode("utf-8", errors="replace")


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """Ingest a PDF/TXT/MD document into the local RAG index."""
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Supported: {sorted(SUPPORTED_SUFFIXES)}",
        )
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 20 MB limit")
    if not payload:
        raise HTTPException(status_code=400, detail="Empty file")

    text = _extract_text(file.filename, payload)
    if not text.strip():
        raise HTTPException(status_code=400, detail="No extractable text in document")

    try:
        result = get_doc_index().add_document(title=file.filename, text=text)
    except Exception as exc:  # noqa: BLE001 — embedding/backend errors
        logger.exception("Document ingestion failed")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")
    return {"user_id": user_id, **result}


@router.get("")
async def list_documents(user_id: str = Depends(get_current_user_id)):
    """List ingested documents."""
    index = get_doc_index()
    return {
        "items": [
            {"doc_id": doc_id, **meta}
            for doc_id, meta in sorted(index.docs.items(), key=lambda kv: kv[0])
        ],
        "total_chunks": len(index.chunks),
    }


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, user_id: str = Depends(get_current_user_id)):
    """Remove a document and all its chunks from the index."""
    if not get_doc_index().remove_document(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": doc_id}
