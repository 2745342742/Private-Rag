from __future__ import annotations

from collections import defaultdict
from typing import Any, DefaultDict, Dict, Iterable, List


def make_context_candidates(
    chunks: Iterable[Dict[str, Any]],
    *,
    min_chars: int = 1200,
    max_chars: int = 2400,
    per_doc_cap: int = 10,
) -> List[Dict[str, Any]]:
    """从块构建更大、上下文丰富的候选，并按文档平衡。"""
    by_doc: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ch in chunks:
        doc_id = (
            ch.get("doc_id")
            or ch.get("source_id")
            or ch.get("metadata", {}).get("file_id")
        )
        if not doc_id:
            doc_id = "_unknown"
        by_doc[doc_id].append(ch)

    def infer_tags(text: str) -> List[str]:
        tags: List[str] = []
        if "|" in text and "---" in text:
            tags.append("table")
        if "```" in text or "def " in text or "class " in text:
            tags.append("code")
        if any(sym in text for sym in ["%", "+/-", "+/−", "±"]):
            tags.append("numeric")
        if "TODO" in text or "FIXME" in text:
            tags.append("notes")
        return tags

    contexts: List[Dict[str, Any]] = []
    for doc_id, lst in by_doc.items():
        taken = 0
        for ch in lst:
            if taken >= per_doc_cap:
                break
            text = (ch.get("text") or "").strip()
            if not text:
                continue
            snippet = text[:max_chars]
            tags = infer_tags(snippet)
            meta = ch.get("metadata") or {}
            for h in (
                (meta.get("heading") or [])
                if isinstance(meta.get("heading"), list)
                else []
            ):
                if isinstance(h, str):
                    tags.append("heading:" + h.strip()[:50])
            if isinstance(meta.get("headings"), list):
                for h in meta.get("headings"):
                    if isinstance(h, str):
                        tags.append("heading:" + h.strip()[:50])
            contexts.append(
                {
                    "text": snippet,
                    "source_id": doc_id,
                    "page": ch.get("page"),
                    "char_start": 0,
                    "char_end": len(snippet),
                    "tags": tags,
                }
            )
            taken += 1
    return contexts
