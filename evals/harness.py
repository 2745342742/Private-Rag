from __future__ import annotations

import os
from typing import Any, Dict, List

from rich import print as rprint

from config.schema import RootConfig
from evals.datasets.schema import load_and_validate_jsonl
from evals.metrics.qa import em_f1
from evals.reporters import write_markdown_report
from evals.reporters.html import write_html_report
from evals.runners.local_judge import run_local_judge


def run_evals(cfg: RootConfig, config_path: str | None = None) -> None:
    """程序化评测入口（可由脚本直接调用）。"""
    mode = getattr(cfg.evals, "mode", "user")

    if mode == "user":
        if not cfg.evals.dataset_path:
            raise SystemExit("用户模式下未配置 evals.dataset_path")

        local_summary = run_local_judge(
            cfg, cfg.evals.dataset_path, config_path=config_path
        )
        rprint(
            f"[green]本地评判通过率[/green]：{local_summary.get('pass_rate'):.3f}"
        )
        gold_by_id = {
            (ex.item.id or ""): (ex.item.correct_answer or "")
            for ex in load_and_validate_jsonl(cfg.evals.dataset_path)
        }
        md_rows: List[Dict[str, Any]] = []
        for row in local_summary.get("rows") or []:
            ans = row.get("answer") or ""
            ex_id = row.get("id") or ""
            gold = gold_by_id.get(ex_id, "")
            em, f1 = em_f1(ans, gold)
            md_rows.append(
                {
                    "id": ex_id,
                    "latency_ms": int(row.get("latency_ms") or 0),
                    "em": em,
                    "f1": f1,
                    "answer": ans,
                }
            )
        md_report = {
            "project": cfg.project,
            "num_examples": len(md_rows),
            "total_ms": int(local_summary.get("total_ms") or 0),
            "avg_latency_ms": float(local_summary.get("avg_latency_ms") or 0.0),
            "avg_em": sum(r["em"] for r in md_rows) / max(1, len(md_rows)),
            "avg_f1": sum(r["f1"] for r in md_rows) / max(1, len(md_rows)),
            "rows": md_rows,
        }
        if config_path:
            md_report["config_path"] = config_path
        md_path = write_markdown_report(md_report)
        html_path = os.path.join("evals", "reports", "local_summary.html")
        write_html_report(local_summary, html_path)
        rprint(f"[cyan]已写入报告[/cyan]：{md_path} 和 {html_path}")
        return

    if mode == "auto":
        from evals.generator.auto_pipeline import auto_generate_dataset

        rprint("[cyan]正在启动自动生成流水线...[/cyan]")
        summary, rows = auto_generate_dataset(cfg)
        if not rows:
            raise SystemExit(
                "自动评估生成了 0 条数据。请检查语料库是否已摄入且可访问。\n"
                "提示：\n"
                "- 请先通过平台「文档」页上传并完成入库。\n"
                "- 确认 OPENAI_API_KEY / OPENAI_BASE_URL（百炼）与嵌入模型可用。\n"
                "- 确认 Qdrant 已启动且 collection 有数据。\n"
                "- 调整 evals.auto 参数（scan_docs、items_target）以扩大采样范围。"
            )
        rprint(
            f"[green]自动生成数据集[/green]：{summary.sampled} 条 → {summary.dataset_path}"
        )
        local_summary = run_local_judge(
            cfg, summary.dataset_path, config_path=config_path
        )
        html_path = os.path.join("evals", "reports", "local_summary.html")
        write_html_report(local_summary, html_path)
        rprint(
            f"[cyan]本地评判已完成[/cyan]：pass_rate={local_summary.get('pass_rate'):.3f}"
        )
        return

    raise SystemExit(f"未知的 evals.mode：{mode}")
