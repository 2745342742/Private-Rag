from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlparse

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from config.env_utils import (
    _ensure_dotenv_precedence,
    resolve_env_placeholder,
    resolve_openai_base_url,
)
from config.schema import RootConfig, load_config


def load_runtime_cfg(config_path: Optional[str] = None) -> RootConfig:
    _ensure_dotenv_precedence()
    path = config_path or os.getenv("RAG_CONFIG") or "configs/default.china.yaml"
    if not os.path.isabs(path):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        path = str((root / path).resolve())
    return load_config(path)


def _api_key(cfg: RootConfig) -> str:
    key = resolve_env_placeholder(getattr(cfg.env, "openai_api_key", None))
    key = key or os.getenv("OPENAI_API_KEY") or ""
    if not key:
        raise RuntimeError("未配置 OPENAI_API_KEY（百炼 Key）")
    return key


def _base_url(cfg: RootConfig) -> Optional[str]:
    return resolve_openai_base_url(cfg)


def _bypass_qdrant_proxy(url: str) -> None:
    if os.getenv("RAG_QDRANT_USE_PROXY", "").lower() in {"1", "true", "yes"}:
        return
    try:
        host = urlparse(url).hostname
        if not host:
            return
        existing = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
        parts = [p.strip() for p in existing.split(",") if p.strip()]
        if host not in parts:
            parts.append(host)
            joined = ",".join(parts)
            os.environ["NO_PROXY"] = joined
            os.environ["no_proxy"] = joined
    except Exception:
        pass


def build_embeddings(cfg: Optional[RootConfig] = None) -> OpenAIEmbeddings:
    cfg = cfg or load_runtime_cfg()
    dims = getattr(cfg.embeddings, "dimensions", None)
    # 百炼 text-embedding-v* 单次 batch 上限 10
    batch = int(getattr(cfg.embeddings, "batch_size", None) or 10)
    batch = max(1, min(batch, 10))
    kwargs = {
        "model": cfg.embeddings.model,
        "api_key": _api_key(cfg),
        "base_url": _base_url(cfg),
        "check_embedding_ctx_length": False,
        "chunk_size": batch,
    }
    if dims:
        kwargs["dimensions"] = int(dims)
    return OpenAIEmbeddings(**kwargs)


def build_chat_model(
    cfg: Optional[RootConfig] = None, *, model: Optional[str] = None
) -> ChatOpenAI:
    cfg = cfg or load_runtime_cfg()
    return ChatOpenAI(
        model=model or cfg.synthesis.model,
        api_key=_api_key(cfg),
        base_url=_base_url(cfg),
        temperature=0.2,
    )


def qdrant_connection(cfg: Optional[RootConfig] = None) -> dict:
    cfg = cfg or load_runtime_cfg()
    q = cfg.vector_store.custom.qdrant
    url = (
        resolve_env_placeholder(q.url)
        or os.getenv("QDRANT_URL")
        or "http://localhost:6333"
    )
    api_key = resolve_env_placeholder(q.api_key) or os.getenv("QDRANT_API_KEY") or None
    if api_key is not None and not str(api_key).strip():
        api_key = None
    _bypass_qdrant_proxy(url)
    return {
        "url": url,
        "api_key": api_key,
        "collection_name": q.collection,
        "timeout": float(os.getenv("RAG_QDRANT_TIMEOUT", "60")),
    }
