from __future__ import annotations

from typing import Any, Dict, List


def citations_from_chunks(
    chunks: List[Dict[str, Any]], *, max_items: int = 8
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunks:
        doc_id = str(chunk.get("doc_id") or "")
        key = doc_id or (chunk.get("filename") or chunk.get("text", "")[:40])
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "document_id": doc_id or None,
                "doc_id": doc_id or None,
                "filename": chunk.get("filename"),
                "title": chunk.get("title") or chunk.get("filename"),
                "score": chunk.get("score"),
            }
        )
        if len(results) >= max_items:
            break
    return results
