from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import auth
from . import services_eval as eval_svc

router = APIRouter(prefix="/eval", tags=["eval"])


class RunEvalRequest(BaseModel):
    dataset_id: str


@router.get("/datasets")
def list_datasets(
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    items = eval_svc.list_datasets(user["id"])
    return {"items": items}


@router.delete("/datasets/{dataset_id}")
def delete_dataset(
    dataset_id: str,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    try:
        eval_svc.delete_dataset(user["id"], dataset_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/datasets/import")
async def import_dataset(
    name: str = Form(...),
    file: UploadFile | None = File(default=None),
    source_path: str | None = Form(default=None),
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    tmp_path: Path | None = None
    try:
        if file is not None and file.filename:
            suffix = Path(file.filename).suffix or ".jsonl"
            fd, tmp = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            tmp_path = Path(tmp)
            tmp_path.write_bytes(await file.read())
            jsonl_path = tmp_path
        elif source_path:
            jsonl_path = Path(source_path)
            if not jsonl_path.is_absolute():
                jsonl_path = (
                    Path(__file__).resolve().parents[4] / source_path
                ).resolve()
            if not jsonl_path.exists():
                raise HTTPException(status_code=400, detail="source_path 不存在")
        else:
            raise HTTPException(status_code=400, detail="请上传 file 或提供 source_path")
        return eval_svc.import_dataset_from_jsonl(
            user_id=user["id"], name=name.strip(), jsonl_path=jsonl_path
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"导入失败：{exc}") from exc
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


@router.get("/runs")
def list_runs(
    dataset_id: str | None = None,
    limit: int = 50,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    items = eval_svc.list_runs(
        user["id"], dataset_id=dataset_id or None, limit=limit
    )
    return {"items": items}


@router.post("/runs")
def create_run(
    body: RunEvalRequest,
    background_tasks: BackgroundTasks,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    """立即返回 running 任务，评测在后台执行；前端轮询 GET /runs/{id}。"""
    try:
        run = eval_svc.start_eval_run(
            user_id=user["id"], dataset_id=body.dataset_id
        )
    except ValueError as exc:
        # 题库不存在 / 已有任务进行中
        detail = str(exc)
        code = 409 if "进行中" in detail else 404
        raise HTTPException(status_code=code, detail=detail) from exc
    background_tasks.add_task(
        eval_svc.execute_eval_run,
        user_id=user["id"],
        run_id=run["id"],
        dataset_id=body.dataset_id,
    )
    return run


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    try:
        return eval_svc.cancel_eval_run(user_id=user["id"], run_id=run_id)
    except ValueError as exc:
        detail = str(exc)
        code = 404 if "不存在" in detail else 409
        raise HTTPException(status_code=code, detail=detail) from exc


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    try:
        return eval_svc.get_run(user["id"], run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/runs/{run_id}")
def delete_run(
    run_id: str,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    try:
        eval_svc.delete_run(user["id"], run_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
