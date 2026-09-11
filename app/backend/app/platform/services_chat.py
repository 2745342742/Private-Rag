from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterator

from rag_lc.llm import load_runtime_cfg

from . import db

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _serialize_message(row: dict) -> dict[str, Any]:
    citations = row.get("citations_json") or []
    if isinstance(citations, str):
        citations = json.loads(citations)
    return {
        "id": str(row["id"]),
        "role": row["role"],
        "content": row["content"] or "",
        "citations": citations,
        "latency_ms": row.get("latency_ms"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def list_conversations(user_id: str) -> list[dict[str, Any]]:
    with db.get_conn() as conn:
        rows = db.fetchall(
            conn,
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            WHERE user_id = %s
            ORDER BY updated_at DESC
            """,
            (user_id,),
        )
    return [
        {
            "id": str(r["id"]),
            "title": r.get("title"),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        }
        for r in rows
    ]


def create_conversation(user_id: str, title: str | None = None) -> dict[str, Any]:
    with db.get_conn() as conn:
        row = db.fetchone(
            conn,
            """
            INSERT INTO conversations (user_id, title)
            VALUES (%s, %s)
            RETURNING id, title, created_at, updated_at
            """,
            (user_id, title),
        )
    assert row is not None
    return {
        "id": str(row["id"]),
        "title": row.get("title"),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def get_conversation(user_id: str, conversation_id: str) -> dict | None:
    with db.get_conn() as conn:
        return db.fetchone(
            conn,
            """
            SELECT id, user_id, title, created_at, updated_at
            FROM conversations
            WHERE id = %s AND user_id = %s
            """,
            (conversation_id, user_id),
        )


def rename_conversation(
    user_id: str, conversation_id: str, title: str
) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise ValueError("标题不能为空")
    if len(title) > 80:
        title = title[:80]
    with db.get_conn() as conn:
        row = db.fetchone(
            conn,
            """
            UPDATE conversations
            SET title = %s, updated_at = now()
            WHERE id = %s AND user_id = %s
            RETURNING id, title, created_at, updated_at
            """,
            (title, conversation_id, user_id),
        )
    if not row:
        raise ValueError("会话不存在")
    return {
        "id": str(row["id"]),
        "title": row.get("title"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def delete_conversation(user_id: str, conversation_id: str) -> None:
    with db.get_conn() as conn:
        row = db.fetchone(
            conn,
            """
            DELETE FROM conversations
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (conversation_id, user_id),
        )
    if not row:
        raise ValueError("会话不存在")


def list_messages(user_id: str, conversation_id: str) -> list[dict[str, Any]]:
    if not get_conversation(user_id, conversation_id):
        return []
    with db.get_conn() as conn:
        rows = db.fetchall(
            conn,
            """
            SELECT id, role, content, citations_json, latency_ms, created_at
            FROM messages
            WHERE conversation_id = %s
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        )
    return [_serialize_message(r) for r in rows]


def _history_for_rag(conversation_id: str, limit: int = 12) -> list[dict[str, str]]:
    with db.get_conn() as conn:
        rows = db.fetchall(
            conn,
            """
            SELECT role, content
            FROM messages
            WHERE conversation_id = %s AND role IN ('user', 'assistant')
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (conversation_id, limit),
        )
    rows = list(reversed(rows))
    return [{"role": r["role"], "content": r["content"] or ""} for r in rows]


def _citations_from_output(output: dict[str, Any]) -> list[dict[str, Any]]:
    citations = output.get("citations") or []
    chunks = output.get("chunks") or []
    chunk_by_doc = {
        c.get("doc_id"): c for c in chunks if isinstance(c, dict) and c.get("doc_id")
    }
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cit in citations:
        doc_id = cit.get("doc_id") or cit.get("document_id")
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        chunk = chunk_by_doc.get(doc_id) or {}
        filename = chunk.get("filename")
        if not filename:
            path = (chunk.get("metadata") or {}).get("path")
            if isinstance(path, str):
                filename = Path(path).name
        results.append(
            {
                "document_id": doc_id,
                "filename": filename,
                "title": cit.get("title") or chunk.get("title") or filename,
                "score": chunk.get("score"),
            }
        )
    return results


def post_message(user_id: str, conversation_id: str, content: str) -> dict[str, Any]:
    """非流式：内部走流式收集，保持旧 JSON 接口兼容。"""
    user_message = None
    assistant_message = None
    for event in iter_post_message_events(user_id, conversation_id, content):
        if event.get("type") == "user_message":
            user_message = event["message"]
        elif event.get("type") == "done":
            assistant_message = event["assistant_message"]
        elif event.get("type") == "error":
            raise RuntimeError(event.get("detail") or "问答失败")
    if not user_message or not assistant_message:
        raise RuntimeError("问答未完成")
    return {
        "user_message": user_message,
        "assistant_message": assistant_message,
    }


def iter_post_message_events(
    user_id: str, conversation_id: str, content: str
) -> Iterator[dict[str, Any]]:
    """产出可序列化为 SSE 的事件字典。"""
    from rag_lc.chain import iter_answer_query

    conv = get_conversation(user_id, conversation_id)
    if not conv:
        raise ValueError("会话不存在")

    text = (content or "").strip()
    if not text:
        raise ValueError("消息不能为空")

    with db.get_conn() as conn:
        user_row = db.fetchone(
            conn,
            """
            INSERT INTO messages (conversation_id, role, content)
            VALUES (%s, 'user', %s)
            RETURNING id, role, content, citations_json, latency_ms, created_at
            """,
            (conversation_id, text),
        )
        if not conv.get("title"):
            conn.execute(
                "UPDATE conversations SET title = %s, updated_at = now() WHERE id = %s",
                (text[:40], conversation_id),
            )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = now() WHERE id = %s",
                (conversation_id,),
            )

    assert user_row is not None
    yield {"type": "user_message", "message": _serialize_message(user_row)}

    history = _history_for_rag(conversation_id)
    if history and history[-1]["role"] == "user" and history[-1]["content"] == text:
        history = history[:-1]

    cfg = load_runtime_cfg()
    t0 = time.time()
    answer_text = ""
    output: dict[str, Any] = {}

    try:
        for event in iter_answer_query(
            cfg=cfg,
            query=text,
            history=history,
            user_id=user_id,
        ):
            et = event.get("type")
            if et == "status":
                yield {"type": "status", "stage": event.get("stage")}
            elif et == "token":
                piece = event.get("text") or ""
                if piece:
                    yield {"type": "token", "text": piece}
            elif et == "final":
                output = event
                answer_text = event.get("answer_text") or event.get("answer") or ""
    except Exception as exc:
        yield {"type": "error", "detail": str(exc)}
        return

    latency_ms = int((time.time() - t0) * 1000)
    citations = _citations_from_output(output)

    with db.get_conn() as conn:
        asst_row = db.fetchone(
            conn,
            """
            INSERT INTO messages (conversation_id, role, content, citations_json, latency_ms)
            VALUES (%s, 'assistant', %s, %s::jsonb, %s)
            RETURNING id, role, content, citations_json, latency_ms, created_at
            """,
            (
                conversation_id,
                answer_text,
                json.dumps(citations, ensure_ascii=False),
                latency_ms,
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = now() WHERE id = %s",
            (conversation_id,),
        )

    assert asst_row is not None
    yield {
        "type": "done",
        "assistant_message": _serialize_message(asst_row),
    }
