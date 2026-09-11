from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore, RetrievalMode
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from rich import print as rprint

from config.schema import RootConfig

from .llm import build_embeddings, load_runtime_cfg, qdrant_connection


def get_qdrant_client(cfg: Optional[RootConfig] = None) -> QdrantClient:
    cfg = cfg or load_runtime_cfg()
    conn = qdrant_connection(cfg)
    return QdrantClient(
        url=conn["url"],
        api_key=conn["api_key"],
        timeout=conn["timeout"],
        prefer_grpc=False,
    )


def _ensure_collection(cfg: RootConfig, client: QdrantClient, name: str) -> None:
    exists = False
    try:
        if hasattr(client, "collection_exists"):
            exists = bool(client.collection_exists(name))
        else:
            client.get_collection(name)
            exists = True
    except Exception:
        exists = False
    if exists:
        return
    dims = int(getattr(cfg.embeddings, "dimensions", None) or 1024)
    client.create_collection(
        collection_name=name,
        vectors_config=rest.VectorParams(size=dims, distance=rest.Distance.COSINE),
    )
    for field in ("metadata.user_id", "metadata.doc_id"):
        try:
            client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=rest.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass
    rprint(f"[green]已创建 Qdrant collection[/green] name={name} dims={dims}")


def get_vector_store(cfg: Optional[RootConfig] = None) -> QdrantVectorStore:
    cfg = cfg or load_runtime_cfg()
    conn = qdrant_connection(cfg)
    embeddings = build_embeddings(cfg)
    client = get_qdrant_client(cfg)
    name = conn["collection_name"]
    _ensure_collection(cfg, client, name)

    for field in ("metadata.user_id", "metadata.doc_id"):
        try:
            client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=rest.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass

    store = QdrantVectorStore(
        client=client,
        collection_name=name,
        embedding=embeddings,
        retrieval_mode=RetrievalMode.DENSE,
        content_payload_key="page_content",
        metadata_payload_key="metadata",
        validate_collection_config=False,
    )
    rprint(f"[cyan]LangChain Qdrant[/cyan] collection={name}")
    return store


def user_filter(user_id: Optional[str]) -> Optional[rest.Filter]:
    if not user_id:
        return None
    return rest.Filter(
        must=[
            rest.FieldCondition(
                key="metadata.user_id",
                match=rest.MatchValue(value=str(user_id)),
            )
        ]
    )


def scroll_documents(
    cfg: Optional[RootConfig] = None,
    *,
    user_id: Optional[str] = None,
    limit: int = 4000,
) -> List[Document]:
    cfg = cfg or load_runtime_cfg()
    client = get_qdrant_client(cfg)
    conn = qdrant_connection(cfg)
    docs: List[Document] = []
    offset: Any = None
    flt = user_filter(user_id)
    while len(docs) < limit:
        batch_limit = min(256, limit - len(docs))
        kwargs: dict[str, Any] = {
            "collection_name": conn["collection_name"],
            "limit": batch_limit,
            "with_payload": True,
            "with_vectors": False,
        }
        if flt is not None:
            kwargs["scroll_filter"] = flt
        if offset is not None:
            kwargs["offset"] = offset
        points, offset = client.scroll(**kwargs)
        if not points:
            break
        for p in points:
            payload = p.payload or {}
            text = payload.get("page_content") or payload.get("text") or ""
            if not str(text).strip():
                continue
            meta = payload.get("metadata")
            if not isinstance(meta, dict):
                meta = {
                    k: v
                    for k, v in payload.items()
                    if k not in {"page_content", "text", "metadata"}
                }
            meta = dict(meta or {})
            meta["_qdrant_id"] = str(p.id)
            docs.append(Document(page_content=str(text), metadata=meta))
        if offset is None:
            break
    return docs


def delete_by_doc_ids(doc_ids: List[str], cfg: Optional[RootConfig] = None) -> None:
    if not doc_ids:
        return
    cfg = cfg or load_runtime_cfg()
    client = get_qdrant_client(cfg)
    conn = qdrant_connection(cfg)
    if len(doc_ids) == 1 and doc_ids[0] == "*":
        client.delete(
            collection_name=conn["collection_name"],
            points_selector=rest.FilterSelector(filter=rest.Filter()),
        )
        from .retrieve import invalidate_bm25_cache

        invalidate_bm25_cache(None)
        return
    flt = rest.Filter(
        should=[
            rest.FieldCondition(
                key="metadata.doc_id", match=rest.MatchValue(value=str(d))
            )
            for d in doc_ids
        ]
    )
    client.delete(
        collection_name=conn["collection_name"],
        points_selector=rest.FilterSelector(filter=flt),
    )
    from .retrieve import invalidate_bm25_cache

    invalidate_bm25_cache(None)


def wipe_collection(cfg: Optional[RootConfig] = None) -> None:
    delete_by_doc_ids(["*"], cfg=cfg)


def upsert_documents(
    docs: List[Document],
    *,
    cfg: Optional[RootConfig] = None,
    batch_size: int = 10,
) -> int:
    """先按百炼上限分批嵌入，再写入 Qdrant（兼容 LangChain payload 结构）。"""
    import time
    import uuid

    from config.env_utils import build_openai_client, embedding_create_kwargs

    if not docs:
        return 0
    cfg = cfg or load_runtime_cfg()
    get_vector_store(cfg)
    client = get_qdrant_client(cfg)
    conn = qdrant_connection(cfg)
    oai = build_openai_client(cfg)
    model = cfg.embeddings.model
    batch_size = max(1, min(int(batch_size), 10))

    cleaned: List[Document] = []
    for d in docs:
        text = (d.page_content or "").strip()
        if not text:
            continue
        if len(text) > 6000:
            text = text[:6000]
        cleaned.append(Document(page_content=text, metadata=dict(d.metadata or {})))

    written = 0
    for start in range(0, len(cleaned), batch_size):
        batch = cleaned[start : start + batch_size]
        texts = [d.page_content for d in batch]
        assert len(texts) <= 10
        last_err: Exception | None = None
        vectors: List[List[float]] | None = None
        for attempt in range(1, 6):
            try:
                resp = oai.embeddings.create(
                    **embedding_create_kwargs(cfg, model=model, input=texts)
                )
                data = sorted(resp.data, key=lambda x: x.index)
                vectors = [item.embedding for item in data]
                if len(vectors) != len(texts):
                    raise RuntimeError(
                        f"嵌入返回数量不匹配：期望 {len(texts)}，实际 {len(vectors)}"
                    )
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                delay = min(8.0, 0.8 * (2 ** (attempt - 1)))
                rprint(
                    f"[yellow]嵌入失败 batch={len(texts)}（{type(exc).__name__}: {exc}），"
                    f"{delay:.1f}s 后重试 {attempt}/5…[/yellow]"
                )
                time.sleep(delay)
        if last_err is not None or vectors is None:
            raise RuntimeError(f"嵌入失败：{last_err}") from last_err

        points = []
        for doc, vec in zip(batch, vectors):
            points.append(
                rest.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vec,
                    payload={
                        "page_content": doc.page_content,
                        "metadata": dict(doc.metadata or {}),
                    },
                )
            )
        for attempt in range(1, 6):
            try:
                client.upsert(collection_name=conn["collection_name"], points=points)
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                delay = min(8.0, 0.8 * (2 ** (attempt - 1)))
                rprint(
                    f"[yellow]写入 Qdrant 失败（{type(exc).__name__}: {exc}），"
                    f"{delay:.1f}s 后重试 {attempt}/5…[/yellow]"
                )
                time.sleep(delay)
        if last_err is not None:
            raise RuntimeError(f"写入 Qdrant 失败：{last_err}") from last_err
        written += len(points)
        rprint(f"[dim]已写入 {written}/{len(cleaned)} 个分块[/dim]")
    return written
