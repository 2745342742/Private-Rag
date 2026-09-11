from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, List, Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rich import print as rprint

from config.schema import RootConfig

from .llm import load_runtime_cfg
from .store import delete_by_doc_ids, upsert_documents, wipe_collection


def _docs_to_text(docs: List[Document]) -> str:
    parts = [(d.page_content or "").strip() for d in docs]
    return "\n\n".join(p for p in parts if p).strip()


def _read_file_text(path: Path) -> str:
    """用 LangChain Document Loader 解析文件为纯文本。"""
    ext = path.suffix.lower()
    file_path = str(path)

    try:
        if ext == ".pdf":
            from langchain_community.document_loaders import PyPDFLoader

            docs = PyPDFLoader(file_path).load()
        elif ext == ".docx":
            from langchain_community.document_loaders import Docx2txtLoader

            docs = Docx2txtLoader(file_path).load()
        elif ext in {".html", ".htm"}:
            from langchain_community.document_loaders import BSHTMLLoader

            docs = BSHTMLLoader(file_path, open_encoding="utf-8").load()
        elif ext == ".md":
            from langchain_community.document_loaders import TextLoader

            docs = TextLoader(file_path, encoding="utf-8").load()
        elif ext == ".csv":
            from langchain_community.document_loaders import CSVLoader

            docs = CSVLoader(file_path, encoding="utf-8").load()
        elif ext == ".txt":
            from langchain_community.document_loaders import TextLoader

            docs = TextLoader(file_path, encoding="utf-8").load()
        elif ext == ".doc":
            raise ValueError("暂不支持旧版 .doc，请另存为 .docx 后再上传")
        else:
            from langchain_community.document_loaders import TextLoader

            docs = TextLoader(file_path, encoding="utf-8").load()
    except ImportError as exc:
        raise ImportError(
            f"解析 {ext} 缺少依赖：{exc}. 请安装对应包后重试。"
        ) from exc

    text = _docs_to_text(docs)
    if ext == ".docx" and not text:
        raise ValueError("Word 文档未解析到可用文本（可能为空或仅含图片）")
    return text


def _splitter(cfg: RootConfig) -> RecursiveCharacterTextSplitter:
    lo, hi = cfg.chunking.target_token_range
    # 粗略按字符：token ≈ 4 chars
    chunk_size = max(400, int(hi) * 4)
    overlap = max(50, int(cfg.chunking.overlap_tokens) * 4)
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=min(overlap, chunk_size // 4),
        separators=["\n\n", "\n", "。", "！", "？", ". ", " ", ""],
    )


def ingest_file(
    *,
    file_path: Path,
    user_id: Optional[str] = None,
    cfg: Optional[RootConfig] = None,
) -> dict[str, Any]:
    cfg = cfg or load_runtime_cfg()
    path = Path(file_path).resolve()
    text = _read_file_text(path)
    if not text:
        raise ValueError("文档内容为空，无法入库")

    doc_id = hashlib.sha1(str(path).encode("utf-8")).hexdigest()
    base_meta = {
        "doc_id": doc_id,
        "path": str(path),
        "filename": path.name,
        "title": path.name,
    }
    if user_id:
        base_meta["user_id"] = str(user_id)

    splitter = _splitter(cfg)
    chunks = splitter.create_documents([text], metadatas=[base_meta])
    prepared: List[Document] = []
    for i, c in enumerate(chunks):
        body = (c.page_content or "").strip()
        if not body:
            continue
        meta = dict(c.metadata or {})
        meta["chunk_index"] = i
        meta["doc_id"] = doc_id
        if user_id:
            meta["user_id"] = str(user_id)
        prepared.append(Document(page_content=body, metadata=meta))

    written = upsert_documents(prepared, cfg=cfg, batch_size=10)
    from .retrieve import invalidate_bm25_cache

    invalidate_bm25_cache(str(user_id) if user_id else None)
    rprint(f"[dim]LangChain 入库[/dim] file={path.name} chunks={written}")
    return {
        "vector_doc_id": doc_id,
        "chunk_count": written,
        "path": str(path),
    }


__all__ = [
    "ingest_file",
    "delete_by_doc_ids",
    "wipe_collection",
]
