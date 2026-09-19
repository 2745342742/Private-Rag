from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from evals.datasets.schema import load_and_validate_jsonl
from evals.runners.local_judge import run_local_judge

from rag_lc.llm import load_runtime_cfg

from . import db

PROJECT_ROOT = Path(__file__).resolve().parents[4]

# 进程内取消信号：run_id -> Event（BackgroundTasks 与 API 同进程时生效）
_CANCEL_EVENTS: dict[str, threading.Event] = {}
_CANCEL_LOCK = threading.Lock()


def _get_cancel_event(run_id: str) -> threading.Event:
    with _CANCEL_LOCK:
        ev = _CANCEL_EVENTS.get(run_id)
        if ev is None:
            ev = threading.Event()
            _CANCEL_EVENTS[run_id] = ev
        return ev


def _clear_cancel_event(run_id: str) -> None:
    with _CANCEL_LOCK:
        _CANCEL_EVENTS.pop(run_id, None)


def list_datasets(user_id: str) -> list[dict[str, Any]]:
    with db.get_conn() as conn:
        rows = db.fetchall(
            conn,
            """
            SELECT d.id, d.name, d.created_at,
                   (SELECT COUNT(*) FROM eval_items i WHERE i.dataset_id = d.id) AS item_count
            FROM eval_datasets d
            WHERE d.user_id = %s
            ORDER BY d.created_at DESC
            """,
            (user_id,),
        )
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "item_count": int(r["item_count"] or 0),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        }
        for r in rows
    ]


def delete_dataset(user_id: str, dataset_id: str) -> None:
    with db.get_conn() as conn:
        row = db.fetchone(
            conn,
            """
            DELETE FROM eval_datasets
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (dataset_id, user_id),
        )
        if not row:
            raise ValueError("题库不存在")


def import_dataset_from_jsonl(
    *, user_id: str, name: str, jsonl_path: Path
) -> dict[str, Any]:
    rows = load_and_validate_jsonl(jsonl_path)
    with db.get_conn() as conn:
        ds = db.fetchone(
            conn,
            """
            INSERT INTO eval_datasets (user_id, name)
            VALUES (%s, %s)
            RETURNING id, name, created_at
            """,
            (user_id, name),
        )
        assert ds is not None
        for ex in rows:
            conn.execute(
                """
                INSERT INTO eval_items (dataset_id, question, correct_answer, citation_text)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    ds["id"],
                    ex.item.question,
                    ex.item.correct_answer,
                    ex.item.citation_text or "",
                ),
            )
    return {
        "dataset": {
            "id": str(ds["id"]),
            "name": ds["name"],
            "created_at": ds["created_at"].isoformat(),
        },
        "imported_count": len(rows),
    }


def _write_temp_jsonl(dataset_id: str) -> Path:
    out = PROJECT_ROOT / "evals" / "datasets" / f"_runtime_{dataset_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with db.get_conn() as conn:
        items = db.fetchall(
            conn,
            """
            SELECT id, question, correct_answer, citation_text
            FROM eval_items WHERE dataset_id = %s
            ORDER BY id ASC
            """,
            (dataset_id,),
        )
    with out.open("w", encoding="utf-8") as f:
        for it in items:
            payload = {
                "item": {
                    "id": str(it["id"]),
                    "question": it["question"],
                    "correct_answer": it["correct_answer"],
                    "citation_text": it["citation_text"] or "",
                }
            }
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return out


def _run_counts(conn, *, run_id: str, dataset_id: str) -> tuple[int, int, int]:
    """返回 (result_count, passed_count, item_total)。"""
    agg = db.fetchone(
        conn,
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN decision = 'pass' THEN 1 ELSE 0 END), 0) AS passed
        FROM eval_results WHERE run_id = %s
        """,
        (run_id,),
    )
    total_items = db.fetchone(
        conn,
        "SELECT COUNT(*) AS c FROM eval_items WHERE dataset_id = %s",
        (dataset_id,),
    )
    result_count = int((agg or {}).get("total") or 0)
    passed = int((agg or {}).get("passed") or 0)
    item_total = int((total_items or {}).get("c") or 0)
    return result_count, passed, item_total


def _persist_eval_result(run_id: str, row: dict[str, Any]) -> None:
    """单题结果立即落库；缺 item_id 时跳过（避免外键失败）。"""
    item_id = row.get("id")
    if not item_id:
        return
    judge = row.get("judge") or {}
    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO eval_results
              (run_id, item_id, model_answer, decision, correctness, grounding, rationale)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                item_id,
                row.get("answer") or "",
                judge.get("decision") or "fail",
                judge.get("correctness"),
                judge.get("grounding"),
                judge.get("rationale"),
            ),
        )


def start_eval_run(*, user_id: str, dataset_id: str) -> dict[str, Any]:
    """创建 running 状态的评分任务并立即返回（供后台执行）。"""
    with db.get_conn() as conn:
        ds = db.fetchone(
            conn,
            "SELECT id, name FROM eval_datasets WHERE id = %s AND user_id = %s",
            (dataset_id, user_id),
        )
        if not ds:
            raise ValueError("题库不存在")
        running = db.fetchone(
            conn,
            """
            SELECT id FROM eval_runs
            WHERE user_id = %s AND status = 'running'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        if running:
            raise ValueError("已有评分任务在进行中，请等待完成后再启动")
        run = db.fetchone(
            conn,
            """
            INSERT INTO eval_runs (user_id, dataset_id, status)
            VALUES (%s, %s, 'running')
            RETURNING id
            """,
            (user_id, dataset_id),
        )
        assert run is not None
        run_id = str(run["id"])
    return get_run(user_id, run_id)


def execute_eval_run(*, user_id: str, run_id: str, dataset_id: str) -> None:
    """后台执行评测：逐题落库，结束后更新 run 状态。"""
    cancel_event = _get_cancel_event(run_id)
    try:
        with db.get_conn() as conn:
            owned = db.fetchone(
                conn,
                """
                SELECT id, status FROM eval_runs
                WHERE id = %s AND user_id = %s AND dataset_id = %s
                """,
                (run_id, user_id, dataset_id),
            )
            if not owned:
                print(f"[eval] 跳过未知 run={run_id}")
                return
            if owned.get("status") == "cancelled" or cancel_event.is_set():
                print(f"[eval] run={run_id} 已取消，跳过执行")
                return

        jsonl_path = _write_temp_jsonl(dataset_id)
        cfg = load_runtime_cfg()
        persist_lock = threading.Lock()

        def on_result(row: dict[str, Any]) -> None:
            try:
                with persist_lock:
                    _persist_eval_result(run_id, row)
            except Exception as exc:  # noqa: BLE001
                print(f"[eval] 逐题落库失败 item={row.get('id')}: {exc}")

        summary = run_local_judge(
            cfg,
            jsonl_path,
            config_path=_cfg_hint(),
            user_id=user_id,
            on_result=on_result,
            cancel_check=cancel_event.is_set,
        )
        was_cancelled = bool(summary.get("cancelled")) or cancel_event.is_set()

        with db.get_conn() as conn:
            result_count, passed, _item_total = _run_counts(
                conn, run_id=run_id, dataset_id=dataset_id
            )
            pass_rate = (passed / result_count) if result_count > 0 else 0.0
            final_status = "cancelled" if was_cancelled else "succeeded"
            # 仅当仍为 running 时收尾，避免覆盖用户已取消 / 其它终态
            updated = db.fetchone(
                conn,
                """
                UPDATE eval_runs
                SET status = %s, pass_rate = %s, finished_at = now()
                WHERE id = %s AND status = 'running'
                RETURNING id
                """,
                (final_status, pass_rate, run_id),
            )
        if updated:
            print(
                f"[eval] run={run_id} {final_status} "
                f"results={result_count} pass_rate={pass_rate:.3f}"
            )
        else:
            print(f"[eval] run={run_id} 收尾跳过（状态已非 running）")
    except Exception as exc:  # noqa: BLE001
        print(f"[eval] run={run_id} 失败：{exc}")
        try:
            with db.get_conn() as conn:
                result_count, passed, _item_total = _run_counts(
                    conn, run_id=run_id, dataset_id=dataset_id
                )
                pass_rate = (passed / result_count) if result_count > 0 else None
                conn.execute(
                    """
                    UPDATE eval_runs
                    SET status = 'failed', pass_rate = %s, finished_at = now()
                    WHERE id = %s AND status = 'running'
                    """,
                    (pass_rate, run_id),
                )
        except Exception as mark_exc:  # noqa: BLE001
            print(f"[eval] 标记 failed 失败：{mark_exc}")
    finally:
        _clear_cancel_event(run_id)


def cancel_eval_run(*, user_id: str, run_id: str) -> dict[str, Any]:
    """请求取消进行中的评分；已启动的单题可能仍会跑完。"""
    # 先发取消信号，尽快打断提交新题
    _get_cancel_event(run_id).set()
    with db.get_conn() as conn:
        run = db.fetchone(
            conn,
            """
            SELECT id, dataset_id, status FROM eval_runs
            WHERE id = %s AND user_id = %s
            """,
            (run_id, user_id),
        )
        if not run:
            raise ValueError("评分任务不存在")
        if run["status"] != "running":
            raise ValueError("任务未在进行中，无法取消")
        result_count, passed, _item_total = _run_counts(
            conn, run_id=run_id, dataset_id=str(run["dataset_id"])
        )
        pass_rate = (passed / result_count) if result_count > 0 else None
        updated = db.fetchone(
            conn,
            """
            UPDATE eval_runs
            SET status = 'cancelled', pass_rate = %s, finished_at = now()
            WHERE id = %s AND user_id = %s AND status = 'running'
            RETURNING id
            """,
            (pass_rate, run_id, user_id),
        )
        if not updated:
            raise ValueError("任务未在进行中，无法取消")
    print(f"[eval] run={run_id} 已请求取消")
    return get_run(user_id, run_id)


def run_eval(*, user_id: str, dataset_id: str) -> dict[str, Any]:
    """同步兼容入口：创建并立即在当前线程执行（CLI/测试用）。"""
    run = start_eval_run(user_id=user_id, dataset_id=dataset_id)
    execute_eval_run(
        user_id=user_id, run_id=run["id"], dataset_id=dataset_id
    )
    return get_run(user_id, run["id"])


def _cfg_hint() -> str:
    import os

    return os.getenv("RAG_CONFIG") or "configs/default.china.yaml"


def list_runs(
    user_id: str, *, dataset_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 100))
    with db.get_conn() as conn:
        if dataset_id:
            rows = db.fetchall(
                conn,
                """
                SELECT r.id, r.dataset_id, d.name AS dataset_name, r.status, r.pass_rate,
                       r.created_at, r.finished_at,
                       (SELECT COUNT(*) FROM eval_results er WHERE er.run_id = r.id) AS result_count,
                       (SELECT COUNT(*) FROM eval_items i WHERE i.dataset_id = r.dataset_id) AS item_total
                FROM eval_runs r
                JOIN eval_datasets d ON d.id = r.dataset_id
                WHERE r.user_id = %s AND r.dataset_id = %s
                ORDER BY r.created_at DESC
                LIMIT %s
                """,
                (user_id, dataset_id, limit),
            )
        else:
            rows = db.fetchall(
                conn,
                """
                SELECT r.id, r.dataset_id, d.name AS dataset_name, r.status, r.pass_rate,
                       r.created_at, r.finished_at,
                       (SELECT COUNT(*) FROM eval_results er WHERE er.run_id = r.id) AS result_count,
                       (SELECT COUNT(*) FROM eval_items i WHERE i.dataset_id = r.dataset_id) AS item_total
                FROM eval_runs r
                JOIN eval_datasets d ON d.id = r.dataset_id
                WHERE r.user_id = %s
                ORDER BY r.created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
    return [
        {
            "id": str(r["id"]),
            "dataset_id": str(r["dataset_id"]),
            "dataset_name": r.get("dataset_name") or "",
            "status": r["status"],
            "pass_rate": r.get("pass_rate"),
            "result_count": int(r.get("result_count") or 0),
            "item_total": int(r.get("item_total") or 0),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "finished_at": r["finished_at"].isoformat() if r.get("finished_at") else None,
        }
        for r in rows
    ]


def delete_run(user_id: str, run_id: str) -> None:
    with db.get_conn() as conn:
        row = db.fetchone(
            conn,
            """
            DELETE FROM eval_runs
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (run_id, user_id),
        )
        if not row:
            raise ValueError("评分任务不存在")


def get_run(user_id: str, run_id: str) -> dict[str, Any]:
    with db.get_conn() as conn:
        run = db.fetchone(
            conn,
            """
            SELECT r.id, r.dataset_id, d.name AS dataset_name, r.status, r.pass_rate,
                   r.created_at, r.finished_at
            FROM eval_runs r
            JOIN eval_datasets d ON d.id = r.dataset_id
            WHERE r.id = %s AND r.user_id = %s
            """,
            (run_id, user_id),
        )
        if not run:
            raise ValueError("评分任务不存在")
        result_count, passed, item_total = _run_counts(
            conn, run_id=str(run["id"]), dataset_id=str(run["dataset_id"])
        )
        results = db.fetchall(
            conn,
            """
            SELECT r.item_id, r.model_answer, r.decision, r.correctness, r.grounding,
                   r.rationale, i.question, i.correct_answer
            FROM eval_results r
            JOIN eval_items i ON i.id = r.item_id
            WHERE r.run_id = %s
            ORDER BY i.id
            """,
            (run_id,),
        )
    live_pass = (passed / result_count) if result_count > 0 else run.get("pass_rate")
    return {
        "id": str(run["id"]),
        "dataset_id": str(run["dataset_id"]),
        "dataset_name": run.get("dataset_name") or "",
        "status": run["status"],
        "pass_rate": live_pass if run["status"] == "running" else run.get("pass_rate"),
        "result_count": result_count,
        "item_total": item_total,
        "created_at": run["created_at"].isoformat() if run.get("created_at") else None,
        "finished_at": run["finished_at"].isoformat() if run.get("finished_at") else None,
        "results": [
            {
                "item_id": str(r["item_id"]),
                "question": r["question"],
                "correct_answer": r["correct_answer"],
                "model_answer": r["model_answer"],
                "decision": r["decision"],
                "correctness": r.get("correctness"),
                "grounding": r.get("grounding"),
                "rationale": r.get("rationale"),
            }
            for r in results
        ],
    }
