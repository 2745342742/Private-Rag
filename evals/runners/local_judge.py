from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from rich import print as rprint

from config.env_utils import build_openai_client, uses_chat_completions_api
from config.schema import RootConfig
from evals.datasets.schema import load_and_validate_jsonl
from evals.generator.canonicalize import canonicalize_answer
from evals.graders.judge_prompts import SINGLE_RUBRIC_QA_GROUNDED
from evals.graders.schema import JudgeDecision
from rag_lc.chain import answer_query

OnResultCallback = Callable[[Dict[str, Any]], None]


def _eval_max_workers() -> int:
    raw = (os.getenv("EVAL_MAX_WORKERS") or "2").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 2
    return max(1, min(n, 8))


def _heuristic_judge(
    model_answer: str, correct_answer: str, citation_text: str
) -> JudgeDecision:
    ma = canonicalize_answer(model_answer or "")
    ca = canonicalize_answer(correct_answer or "")
    ct = (citation_text or "").lower()
    correctness = 1.0 if ma == ca or ca in ma or ma in ca else 0.0
    grounding = 1.0 if ca and ca in ct else (0.5 if ca and ca in ma else 0.0)
    decision = "pass" if correctness >= 0.8 and grounding >= 0.5 else "fail"
    return JudgeDecision(
        decision=decision,
        correctness=correctness,
        grounding=grounding,
        rationale="heuristic",
    )


def _llm_judge(
    cfg: RootConfig, model_answer: str, correct_answer: str, citation_text: str
) -> JudgeDecision:
    client = build_openai_client(cfg)
    prompt = SINGLE_RUBRIC_QA_GROUNDED
    payload = {
        "model_answer": model_answer,
        "correct_answer": correct_answer,
        "citation_text": citation_text,
    }
    text = ""
    try:
        if uses_chat_completions_api(cfg):
            resp = client.chat.completions.create(
                model=cfg.evals.judge.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
            )
            text = (resp.choices[0].message.content or "") if resp.choices else ""
        else:
            resp = client.responses.create(
                model=cfg.evals.judge.model,
                input=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            )
            text = getattr(resp, "output_text", "") or ""
        data = json.loads(text)
        return JudgeDecision(**data)
    except Exception:
        return _heuristic_judge(model_answer, correct_answer, citation_text)


def _fail_row(
    *,
    item_id: Optional[str],
    question: str,
    latency_ms: int,
    exc: BaseException,
) -> Dict[str, Any]:
    msg = f"{type(exc).__name__}: {exc}"
    return {
        "id": item_id,
        "question": question,
        "answer": "",
        "judge": {
            "decision": "fail",
            "correctness": 0.0,
            "grounding": 0.0,
            "rationale": f"error: {msg}"[:2000],
        },
        "latency_ms": latency_ms,
        "error": msg,
    }


def run_local_judge(
    cfg: RootConfig,
    dataset_path: str | Path,
    config_path: str | None = None,
    *,
    user_id: Optional[str] = None,
    on_result: Optional[OnResultCallback] = None,
    max_workers: Optional[int] = None,
) -> Dict[str, Any]:
    """逐题评测；单题异常记为 fail，不中断整次跑批。

    on_result: 每题完成后回调（可用于逐题落库），在工作线程中调用。
    max_workers: 覆盖环境变量 EVAL_MAX_WORKERS（默认 2）。
    """
    rows = load_and_validate_jsonl(dataset_path)
    workers = max_workers if max_workers is not None else _eval_max_workers()
    results: List[Dict[str, Any]] = []
    results_lock = threading.Lock()
    t0 = time.time()
    rprint(f"[dim]评测并发 workers={workers}（EVAL_MAX_WORKERS）[/dim]")

    def process_example(ex) -> Dict[str, Any]:
        q = ex.item.question or ""
        item_id = ex.item.id
        rprint(f"[cyan]正在评估[/cyan]：{q[:60]}...")
        t_q = time.time()
        out = None
        last_err: Exception | None = None
        try:
            for _attempt in range(3):
                try:
                    out = answer_query(cfg=cfg, query=q, user_id=user_id)
                    last_err = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    time.sleep(0.8)
            if last_err is not None and out is None:
                raise last_err

            latency_ms = int((time.time() - t_q) * 1000)
            answer_text = ""
            if isinstance(out, dict):
                answer_text = out.get("answer_text") or out.get("answer") or ""

            decision = _heuristic_judge(
                answer_text, ex.item.correct_answer, ex.item.citation_text
            )
            if cfg.evals.judge.model:
                decision = _llm_judge(
                    cfg, answer_text, ex.item.correct_answer, ex.item.citation_text
                )
            return {
                "id": item_id,
                "question": ex.item.question,
                "answer": answer_text,
                "judge": decision.model_dump(),
                "latency_ms": latency_ms,
            }
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.time() - t_q) * 1000)
            rprint(f"[yellow]单题失败，已隔离[/yellow]：{(q or '')[:40]}… ({exc})")
            return _fail_row(
                item_id=item_id, question=q, latency_ms=latency_ms, exc=exc
            )

    def _emit(row: Dict[str, Any]) -> None:
        with results_lock:
            results.append(row)
        if on_result is not None:
            on_result(row)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_example, ex): ex for ex in rows}
        for future in as_completed(futures):
            ex = futures[future]
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001
                row = _fail_row(
                    item_id=getattr(ex.item, "id", None),
                    question=ex.item.question or "",
                    latency_ms=0,
                    exc=exc,
                )
                rprint(f"[yellow]单题 future 异常，已隔离[/yellow]：{exc}")
            _emit(row)

    total_ms = int((time.time() - t0) * 1000)
    n = max(1, len(results))
    pass_rate = sum(1 for r in results if r["judge"]["decision"] == "pass") / n
    error_count = sum(1 for r in results if r.get("error"))
    summary = {
        "project": cfg.project,
        "num_items": len(rows),
        "total_ms": total_ms,
        "avg_latency_ms": sum(r["latency_ms"] for r in results) / n,
        "pass_rate": pass_rate,
        "threshold_pass": pass_rate >= cfg.evals.thresholds.pass_rate,
        "error_count": error_count,
        "max_workers": workers,
        "rows": results,
    }
    if config_path:
        summary["config_path"] = config_path
    return summary
