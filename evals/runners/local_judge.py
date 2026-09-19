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


# 断连 / 超时后的等待：第 1、2、3 次失败分别等 2s、5s、15s，共最多 4 次。
_TRANSIENT_BACKOFF_S = (2.0, 5.0, 15.0)


def _is_transient_api_error(exc: BaseException) -> bool:
    """只重试连接断开、超时、限流；解析错误等立即失败。"""
    markers = (
        "disconnect",
        "timeout",
        "timed out",
        "10060",
        "connection reset",
        "connection aborted",
        "connecterror",
        "apitimeout",
        "apiconnection",
        "remoteprotocol",
        "ratelimit",
        "too many requests",
        "429",
        "502",
        "503",
        "504",
        "连接",
        "超时",
    )
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        blob = f"{type(cur).__name__} {cur}".lower()
        if any(m in blob for m in markers):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


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


def _json_loads_judge(s: str) -> Any:
    """解析裁判输出；容忍 markdown 代码块与尾部多余文字。"""
    import re

    t = (s or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```$", "", t)
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]
    return json.loads(t)


def _model_chain(primary: str, fallback: Optional[str]) -> List[str]:
    models = [primary]
    extra = (fallback or "").strip()
    if extra and extra != primary:
        models.append(extra)
    return models


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
    models = _model_chain(
        cfg.evals.judge.model, getattr(cfg.evals.judge, "fallback_model", None)
    )
    text = ""
    last_err: Exception | None = None
    for index, model in enumerate(models):
        if index:
            rprint(f"[yellow]裁判降级到 {model}[/yellow]")
        backoffs = _TRANSIENT_BACKOFF_S if index == 0 else (2.0,)
        attempts = len(backoffs) + 1
        for attempt in range(attempts):
            try:
                if uses_chat_completions_api(cfg):
                    kwargs: Dict[str, Any] = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {
                                "role": "user",
                                "content": json.dumps(payload, ensure_ascii=False),
                            },
                        ],
                        "temperature": 0,
                    }
                    if getattr(cfg.evals.judge, "structured_outputs", False):
                        kwargs["response_format"] = {"type": "json_object"}
                    resp = client.chat.completions.create(**kwargs)
                    text = (resp.choices[0].message.content or "") if resp.choices else ""
                else:
                    resp = client.responses.create(
                        model=model,
                        input=[
                            {"role": "system", "content": prompt},
                            {
                                "role": "user",
                                "content": json.dumps(payload, ensure_ascii=False),
                            },
                        ],
                    )
                    text = getattr(resp, "output_text", "") or ""
                data = _json_loads_judge(text)
                return JudgeDecision(**data)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                rprint(
                    f"[yellow]LLM judge {model} 第 {attempt + 1}/{attempts} 次失败[/yellow]："
                    f"{type(exc).__name__}: {exc}"
                )
                preview = (text or "").replace("\n", " ")[:160]
                if preview:
                    rprint(f"[dim]judge 原始输出预览：{preview}[/dim]")
                if not _is_transient_api_error(exc) or attempt >= len(backoffs):
                    break
                delay = backoffs[attempt]
                rprint(f"[dim]断连/超时，{delay:.0f}s 后重试 judge[/dim]")
                time.sleep(delay)
        if last_err is not None and not _is_transient_api_error(last_err):
            break

    if last_err is not None:
        rprint(
            f"[yellow]LLM judge 失败，回退 heuristic[/yellow]："
            f"{type(last_err).__name__}: {last_err}"
        )
    else:
        rprint("[yellow]LLM judge 失败，回退 heuristic[/yellow]")
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
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """逐题评测；单题异常记为 fail，不中断整次跑批。

    on_result: 每题完成后回调（可用于逐题落库），在工作线程中调用。
    max_workers: 覆盖环境变量 EVAL_MAX_WORKERS（默认 2）。
    cancel_check: 返回 True 时停止提交/收集后续题目（进行中的题仍可能跑完）。
    """
    rows = load_and_validate_jsonl(dataset_path)
    workers = max_workers if max_workers is not None else _eval_max_workers()
    results: List[Dict[str, Any]] = []
    results_lock = threading.Lock()
    t0 = time.time()
    cancelled = False
    rprint(f"[dim]评测并发 workers={workers}（EVAL_MAX_WORKERS）[/dim]")

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    def process_example(ex) -> Dict[str, Any]:
        q = ex.item.question or ""
        item_id = ex.item.id
        if _cancelled():
            return {
                "id": item_id,
                "question": q,
                "answer": "",
                "judge": {
                    "decision": "fail",
                    "correctness": 0.0,
                    "grounding": 0.0,
                    "rationale": "cancelled",
                },
                "latency_ms": 0,
                "cancelled": True,
            }
        rprint(f"[cyan]正在评估[/cyan]：{q[:60]}...")
        t_q = time.time()
        out = None
        last_err: Exception | None = None
        try:
            models = _model_chain(
                cfg.synthesis.model, getattr(cfg.synthesis, "fallback_model", None)
            )
            for index, model in enumerate(models):
                if _cancelled():
                    return {
                        "id": item_id,
                        "question": q,
                        "answer": "",
                        "judge": {
                            "decision": "fail",
                            "correctness": 0.0,
                            "grounding": 0.0,
                            "rationale": "cancelled",
                        },
                        "latency_ms": int((time.time() - t_q) * 1000),
                        "cancelled": True,
                    }
                if index:
                    rprint(f"[yellow]答题降级到 {model}[/yellow]")
                backoffs = _TRANSIENT_BACKOFF_S if index == 0 else (2.0,)
                attempts = len(backoffs) + 1
                for attempt in range(attempts):
                    if _cancelled():
                        return {
                            "id": item_id,
                            "question": q,
                            "answer": "",
                            "judge": {
                                "decision": "fail",
                                "correctness": 0.0,
                                "grounding": 0.0,
                                "rationale": "cancelled",
                            },
                            "latency_ms": int((time.time() - t_q) * 1000),
                            "cancelled": True,
                        }
                    try:
                        out = answer_query(
                            cfg=cfg, query=q, user_id=user_id, model=model
                        )
                        last_err = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_err = exc
                        rprint(
                            f"[yellow]答题 {model} 第 {attempt + 1}/{attempts} 次失败[/yellow]："
                            f"{type(exc).__name__}: {exc}"
                        )
                        if not _is_transient_api_error(exc) or attempt >= len(backoffs):
                            break
                        delay = backoffs[attempt]
                        rprint(f"[dim]断连/超时，{delay:.0f}s 后重试答题[/dim]")
                        time.sleep(delay)
                if out is not None or (
                    last_err is not None and not _is_transient_api_error(last_err)
                ):
                    break
            if last_err is not None and out is None:
                raise last_err

            latency_ms = int((time.time() - t_q) * 1000)
            answer_text = ""
            if isinstance(out, dict):
                answer_text = out.get("answer_text") or out.get("answer") or ""

            if _cancelled():
                return {
                    "id": item_id,
                    "question": q,
                    "answer": answer_text,
                    "judge": {
                        "decision": "fail",
                        "correctness": 0.0,
                        "grounding": 0.0,
                        "rationale": "cancelled",
                    },
                    "latency_ms": latency_ms,
                    "cancelled": True,
                }

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
        if row.get("cancelled"):
            return
        with results_lock:
            results.append(row)
        if on_result is not None:
            on_result(row)

    executor = ThreadPoolExecutor(max_workers=workers)
    futures: Dict[Any, Any] = {}
    try:
        for ex in rows:
            if _cancelled():
                cancelled = True
                rprint("[yellow]评测已取消，停止提交新题[/yellow]")
                break
            futures[executor.submit(process_example, ex)] = ex
        if futures:
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
                if _cancelled():
                    cancelled = True
                    rprint("[yellow]评测已取消，中止后续题目[/yellow]")
                    break
    finally:
        if cancelled or _cancelled():
            cancelled = True
            executor.shutdown(wait=False, cancel_futures=True)
        else:
            executor.shutdown(wait=True)

    total_ms = int((time.time() - t0) * 1000)
    n = max(1, len(results)) if results else 1
    pass_rate = (
        sum(1 for r in results if r["judge"]["decision"] == "pass") / n if results else 0.0
    )
    error_count = sum(1 for r in results if r.get("error"))
    summary = {
        "project": cfg.project,
        "num_items": len(rows),
        "total_ms": total_ms,
        "avg_latency_ms": sum(r["latency_ms"] for r in results) / n if results else 0.0,
        "pass_rate": pass_rate,
        "threshold_pass": pass_rate >= cfg.evals.thresholds.pass_rate,
        "error_count": error_count,
        "max_workers": workers,
        "cancelled": cancelled or _cancelled(),
        "rows": results,
    }
    if config_path:
        summary["config_path"] = config_path
    return summary
