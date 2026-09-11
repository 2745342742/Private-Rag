from __future__ import annotations

import re
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from rich import print as rprint

from config.schema import RootConfig

from .llm import load_runtime_cfg
from .store import get_vector_store, scroll_documents, user_filter

_RRF_K = 60
# 进程内按用户缓存 BM25；语料变更时需 invalidate
_BM25_CACHE: "OrderedDict[str, BM25Retriever]" = OrderedDict()
_BM25_CACHE_LOCK = threading.Lock()
_BM25_CACHE_MAX_USERS = 32


def _tokenize(text: str) -> List[str]:
    raw = (text or "").lower()
    tokens: List[str] = []
    tokens.extend(re.findall(r"[a-z0-9]{2,}", raw))
    for ch in raw:
        if "\u4e00" <= ch <= "\u9fff":
            tokens.append(ch)
    return tokens


def _doc_key(doc: Document) -> str:
    meta = doc.metadata or {}
    doc_id = meta.get("doc_id") or ""
    # 用正文哈希对齐稠密 / BM25 两侧（稠密结果通常没有 _qdrant_id）
    return f"{doc_id}::{hash(doc.page_content)}"


def _cache_key(user_id: Optional[str]) -> str:
    return str(user_id) if user_id else "__all__"


def invalidate_bm25_cache(user_id: Optional[str] = None) -> None:
    """语料变更后调用。user_id=None 清空全部缓存。"""
    with _BM25_CACHE_LOCK:
        if user_id is None:
            _BM25_CACHE.clear()
            return
        _BM25_CACHE.pop(_cache_key(user_id), None)
        # 无用户语料与按用户缓存可能并存，稳妥起见清掉全局
        _BM25_CACHE.pop("__all__", None)


def _get_bm25_retriever(
    *,
    cfg: RootConfig,
    user_id: Optional[str],
    top_k: int,
) -> Optional[BM25Retriever]:
    key = _cache_key(user_id)
    with _BM25_CACHE_LOCK:
        cached = _BM25_CACHE.get(key)
        if cached is not None:
            _BM25_CACHE.move_to_end(key)
            cached.k = top_k
            rprint(f"[dim]BM25 缓存命中 user={key}[/dim]")
            return cached

    corpus = scroll_documents(cfg, user_id=user_id)
    if not corpus:
        return None

    retriever = BM25Retriever.from_documents(
        corpus,
        preprocess_func=_tokenize,
        k=top_k,
    )
    with _BM25_CACHE_LOCK:
        _BM25_CACHE[key] = retriever
        _BM25_CACHE.move_to_end(key)
        while len(_BM25_CACHE) > _BM25_CACHE_MAX_USERS:
            _BM25_CACHE.popitem(last=False)
    rprint(f"[dim]BM25 已建索引并缓存 user={key} corpus={len(corpus)}[/dim]")
    return retriever


def _rrf_fuse(
    ranked_lists: Sequence[Sequence[Document]],
    *,
    top_k: int,
) -> List[Document]:
    scores: Dict[str, float] = {}
    by_key: Dict[str, Document] = {}
    for docs in ranked_lists:
        for rank, doc in enumerate(docs, start=1):
            key = _doc_key(doc)
            scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank)
            if key not in by_key:
                by_key[key] = doc
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    fused: List[Document] = []
    for key, score in ordered[:top_k]:
        doc = by_key[key]
        meta = dict(doc.metadata or {})
        meta["rrf_score"] = score
        fused.append(Document(page_content=doc.page_content, metadata=meta))
    return fused


def retrieve_documents(
    query: str,
    *,
    cfg: Optional[RootConfig] = None,
    user_id: Optional[str] = None,
) -> List[Document]:
    cfg = cfg or load_runtime_cfg()
    top_k = int(cfg.query.top_k)
    store = get_vector_store(cfg)
    flt = user_filter(user_id)

    dense_docs = store.similarity_search(query, k=top_k, filter=flt)
    rprint(f"[dim]稠密检索命中 {len(dense_docs)}[/dim]")

    bm25_docs: List[Document] = []
    retriever = _get_bm25_retriever(cfg=cfg, user_id=user_id, top_k=top_k)
    if retriever is not None:
        bm25_docs = retriever.invoke(query)
        rprint(f"[dim]BM25 命中 {len(bm25_docs)}[/dim]")

    fused = _rrf_fuse([dense_docs, bm25_docs], top_k=top_k)
    rprint(f"[dim]RRF 融合 {len(fused)}[/dim]")
    return fused


def docs_to_chunks(docs: List[Document]) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    for doc in docs:
        meta = dict(doc.metadata or {})
        filename = meta.get("filename")
        if not filename and isinstance(meta.get("path"), str):
            from pathlib import Path

            filename = Path(meta["path"]).name
        score = meta.get("rrf_score")
        chunks.append(
            {
                "doc_id": meta.get("doc_id"),
                "title": meta.get("title") or filename,
                "filename": filename,
                "text": doc.page_content,
                "score": score,
                "similarity_score": score,
                "metadata": meta,
                "page": meta.get("page"),
            }
        )
    return chunks
