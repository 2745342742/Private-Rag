from __future__ import annotations

import json
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import auth
from . import services_chat as chat_svc

router = APIRouter(prefix="/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    title: str | None = None


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class PostMessageRequest(BaseModel):
    content: str = Field(min_length=1)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("")
def list_conversations(
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    items = chat_svc.list_conversations(user["id"])
    return {"total": len(items), "items": items}


@router.post("")
def create_conversation(
    body: CreateConversationRequest,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    return chat_svc.create_conversation(user["id"], body.title)


@router.patch("/{conversation_id}")
def rename_conversation(
    conversation_id: str,
    body: RenameConversationRequest,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    try:
        return chat_svc.rename_conversation(user["id"], conversation_id, body.title)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    try:
        chat_svc.delete_conversation(user["id"], conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    if not chat_svc.get_conversation(user["id"], conversation_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    items = chat_svc.list_messages(user["id"], conversation_id)
    return {"conversation_id": conversation_id, "items": items}


@router.post("/{conversation_id}/messages")
def post_message(
    conversation_id: str,
    body: PostMessageRequest,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    """兼容旧客户端：一次性 JSON。"""
    try:
        return chat_svc.post_message(user["id"], conversation_id, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"问答失败：{exc}") from exc


@router.post("/{conversation_id}/messages/stream")
def post_message_stream(
    conversation_id: str,
    body: PostMessageRequest,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> StreamingResponse:
    """SSE：user_message / status / token / done / error。"""

    def event_gen() -> Iterator[str]:
        try:
            for event in chat_svc.iter_post_message_events(
                user["id"], conversation_id, body.content
            ):
                yield _sse(event)
        except ValueError as exc:
            yield _sse({"type": "error", "detail": str(exc)})
        except Exception as exc:
            yield _sse({"type": "error", "detail": f"问答失败：{exc}"})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
