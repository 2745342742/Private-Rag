from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from . import auth, db
from . import services_docs as docs_svc

router = APIRouter(prefix="/documents", tags=["documents"])


def _doc_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "filename": row["filename"],
        "title": row.get("title"),
        "status": row["status"],
        "vector_doc_id": row.get("vector_doc_id"),
        "error_message": row.get("error_message"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


@router.get("")
def list_documents(
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    with db.get_conn() as conn:
        rows = db.fetchall(
            conn,
            """
            SELECT id, filename, title, status, vector_doc_id, error_message, created_at
            FROM documents
            WHERE user_id = %s AND status <> 'deleted'
            ORDER BY created_at DESC
            """,
            (user["id"],),
        )
    items = [_doc_dict(r) for r in rows]
    return {"total": len(items), "items": items}


@router.get("/{document_id}")
def get_document(
    document_id: str,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    with db.get_conn() as conn:
        row = db.fetchone(
            conn,
            """
            SELECT id, filename, title, status, vector_doc_id, source_path,
                   error_message, created_at
            FROM documents
            WHERE id = %s AND user_id = %s AND status <> 'deleted'
            """,
            (document_id, user["id"]),
        )
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    text = None
    truncated = False
    path = row.get("source_path")
    if path and Path(path).exists():
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
        if len(raw) > 20000:
            text = raw[:20000]
            truncated = True
        else:
            text = raw
    payload = _doc_dict(row)
    payload["text"] = text
    payload["truncated"] = truncated
    return payload


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    """落盘后立即返回 pending，后台异步入库。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件")

    path = docs_svc.save_upload_file(
        user_id=user["id"], filename=file.filename, content=content
    )
    with db.get_conn() as conn:
        row = db.fetchone(
            conn,
            """
            INSERT INTO documents (user_id, filename, title, source_path, status)
            VALUES (%s, %s, %s, %s, 'pending')
            RETURNING id, filename, title, status, vector_doc_id, error_message, created_at
            """,
            (
                user["id"],
                Path(file.filename).name,
                title or Path(file.filename).stem,
                str(path),
            ),
        )
    assert row is not None
    doc_id = str(row["id"])

    background_tasks.add_task(
        docs_svc.process_document_ingest,
        doc_id=doc_id,
        user_id=user["id"],
        file_path=str(path),
    )
    return {"document": _doc_dict(row)}


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    with db.get_conn() as conn:
        row = db.fetchone(
            conn,
            """
            SELECT id, vector_doc_id, source_path
            FROM documents
            WHERE id = %s AND user_id = %s AND status <> 'deleted'
            """,
            (document_id, user["id"]),
        )
        if not row:
            raise HTTPException(status_code=404, detail="文档不存在")
        if row.get("vector_doc_id"):
            try:
                docs_svc.delete_vectors_by_doc_id(
                    row["vector_doc_id"], user_id=user["id"]
                )
            except Exception:
                pass
        conn.execute(
            """
            UPDATE documents SET status = 'deleted'
            WHERE id = %s
            """,
            (document_id,),
        )
    return {"ok": True}
