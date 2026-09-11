from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from rich import print as rprint

from config.schema import RootConfig
from prompts.loader import load_prompt

from .citations import citations_from_chunks
from .llm import build_chat_model, load_runtime_cfg
from .retrieve import docs_to_chunks, retrieve_documents


def _format_context(chunks: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for i, c in enumerate(chunks, start=1):
        name = c.get("filename") or c.get("title") or c.get("doc_id") or f"chunk-{i}"
        parts.append(f"[{i}] ({name})\n{c.get('text') or ''}")
    return "\n\n".join(parts)


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def _build_messages(
    *,
    cfg: RootConfig,
    query: str,
    history: Optional[List[Dict[str, str]]],
    chunks: List[Dict[str, Any]],
) -> list:
    try:
        system_prompt = load_prompt("system/assistant.md")
    except Exception:
        system_prompt = (
            "你是知识库助手。仅依据提供的上下文回答；不足时说明无法从资料中找到。"
            "回答中提及来源文件名。"
        )

    context = _format_context(chunks) if chunks else "（未检索到相关片段）"
    messages = [
        SystemMessage(
            content=(f"{system_prompt}\n\n下方为检索上下文：\n{context}")
        )
    ]
    if history:
        for m in history:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=query))
    return messages


def iter_answer_query(
    store=None,
    cfg: Optional[RootConfig] = None,
    query: str = "",
    history: Optional[List[Dict[str, str]]] = None,
    *,
    user_id: Optional[str] = None,
) -> Iterator[Dict[str, Any]]:
    """流式 RAG：依次产出 status / token / final 事件。"""
    _ = store
    cfg = cfg or load_runtime_cfg()
    q = (query or "").strip()
    if not q:
        raise ValueError("query 不能为空")

    yield {"type": "status", "stage": "retrieving"}
    rprint("[bold]LangChain RAG[/bold]：检索中…")
    docs = retrieve_documents(q, cfg=cfg, user_id=user_id)
    chunks = docs_to_chunks(docs)

    yield {"type": "status", "stage": "generating"}
    messages = _build_messages(cfg=cfg, query=q, history=history, chunks=chunks)
    llm = build_chat_model(cfg)
    rprint("[cyan]正在流式生成回答…[/cyan]")

    parts: List[str] = []
    for chunk in llm.stream(messages):
        piece = _content_to_text(getattr(chunk, "content", None))
        if not piece:
            continue
        parts.append(piece)
        yield {"type": "token", "text": piece}

    answer_text = "".join(parts)
    max_cite = getattr(getattr(cfg.query, "citations", None), "max_per_source", 8) or 8
    citations = citations_from_chunks(chunks, max_items=int(max_cite))
    rprint("[green]合成完成[/green]")
    yield {
        "type": "final",
        "answer_text": answer_text,
        "answer": answer_text,
        "citations": citations,
        "chunks": chunks,
    }


def answer_query(
    store=None,
    cfg: Optional[RootConfig] = None,
    query: str = "",
    history: Optional[List[Dict[str, str]]] = None,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """兼容旧签名：收集流式结果后一次性返回。"""
    final: Dict[str, Any] = {}
    for event in iter_answer_query(
        store=store,
        cfg=cfg,
        query=query,
        history=history,
        user_id=user_id,
    ):
        if event.get("type") == "final":
            final = event
    if not final:
        raise RuntimeError("生成未返回最终结果")
    return {
        "answer_text": final.get("answer_text") or "",
        "answer": final.get("answer") or final.get("answer_text") or "",
        "citations": final.get("citations") or [],
        "chunks": final.get("chunks") or [],
    }
