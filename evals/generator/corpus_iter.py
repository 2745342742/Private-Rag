from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any, Dict, Generator, Optional

from config.schema import RootConfig
from rag_lc.store import scroll_documents


def iterate_chunks(
    cfg: RootConfig, max_docs: Optional[int] = None, max_chars_per_doc: int = 8000
) -> Generator[Dict[str, Any], None, None]:
    """? Qdrant?LangChain payload???? chunk dict????????????"""
    try:
        docs = scroll_documents(cfg, user_id=None, limit=max_docs or 4000)
        yielded = 0
        for doc in docs:
            meta = dict(doc.metadata or {})
            text = (doc.page_content or "")[:max_chars_per_doc]
            if not text:
                continue
            yield {
                "doc_id": meta.get("doc_id"),
                "text": text,
                "page": meta.get("page"),
                "metadata": meta,
            }
            yielded += 1
            if max_docs and yielded >= max_docs:
                return
        if yielded:
            return
    except Exception:
        pass

    data_dirs = [Path(p) for p in getattr(cfg.data, "paths", []) or []]
    include_exts = set((getattr(cfg.data, "include_extensions", None) or []))
    exclude_globs = list(getattr(cfg.data, "exclude_globs", []) or [])

    files: list[Path] = []
    for d in data_dirs:
        root = d if d.is_absolute() else (Path.cwd() / d)
        if not root.exists() or not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if include_exts and p.suffix.lower() not in {e.lower() for e in include_exts}:
                continue
            if any(fnmatch.fnmatch(str(p), pat) for pat in exclude_globs):
                continue
            files.append(p)

    if not files:
        raise NotImplementedError(
            "????????????????????????? data.paths?"
        )

    step = 2000
    max_file_count = max_docs or len(files)
    for i, path in enumerate(files):
        if i >= max_file_count:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not text:
            continue
        for j in range(0, min(len(text), max_chars_per_doc), step):
            chunk_text = text[j : j + step]
            if not chunk_text:
                continue
            yield {
                "doc_id": str(path),
                "text": chunk_text,
                "page": None,
                "metadata": {"file_name": os.path.basename(str(path))},
            }
