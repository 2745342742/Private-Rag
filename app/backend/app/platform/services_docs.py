from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from rag_lc.ingest import delete_by_doc_ids, ingest_file
from rag_lc.llm import load_runtime_cfg

from . import db

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def user_upload_dir(user_id: str) -> Path:
    root = PROJECT_ROOT / "data" / "user_uploads" / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def ingest_file_for_user(*, user_id: str, file_path: Path) -> dict[str, Any]:
    cfg = load_runtime_cfg()
    return ingest_file(file_path=file_path, user_id=user_id, cfg=cfg)


def delete_vectors_by_doc_id(
    vector_doc_id: str, *, user_id: str | None = None
) -> None:
    if not vector_doc_id:
        return
    delete_by_doc_ids([vector_doc_id])
    _ = user_id


def save_upload_file(*, user_id: str, filename: str, content: bytes) -> Path:
    safe_name = Path(filename).name
    dest = user_upload_dir(user_id) / f"{uuid4().hex[:8]}_{safe_name}"
    dest.write_bytes(content)
    return dest


def process_document_ingest(*, doc_id: str, user_id: str, file_path: str) -> None:
    """后台任务：pending → processing → ready / failed。"""
    path = Path(file_path)
    with db.get_conn() as conn:
        row = db.fetchone(
            conn,
            """
            SELECT id, status FROM documents
            WHERE id = %s AND user_id = %s
            """,
            (doc_id, user_id),
        )
        if not row or row["status"] in {"deleted", "ready"}:
            return
        conn.execute(
            """
            UPDATE documents
            SET status = 'processing', error_message = NULL
            WHERE id = %s AND status IN ('pending', 'processing', 'failed')
            """,
            (doc_id,),
        )

    try:
        if not path.exists():
            raise FileNotFoundError(f"上传文件不存在：{path}")
        result = ingest_file_for_user(user_id=user_id, file_path=path)
        with db.get_conn() as conn:
            conn.execute(
                """
                UPDATE documents
                SET status = 'ready', vector_doc_id = %s, error_message = NULL
                WHERE id = %s AND status = 'processing'
                """,
                (result.get("vector_doc_id"), doc_id),
            )
    except Exception as exc:
        with db.get_conn() as conn:
            conn.execute(
                """
                UPDATE documents
                SET status = 'failed', error_message = %s
                WHERE id = %s AND status = 'processing'
                """,
                (str(exc)[:500], doc_id),
            )
