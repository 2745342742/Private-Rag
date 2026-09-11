from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Dict
from datetime import datetime, timezone


def write_html_report(summary: Dict[str, Any], out_path: str | Path) -> None:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    head = "<html><head><meta charset='utf-8'><title>RAG 评估</title></head><body>"
    tail = "</body></html>"
    body = ["<h1>RAG 评估摘要</h1>"]
    ts = datetime.now(timezone.utc).isoformat()
    body.append(f"<div><em>生成时间：{escape(ts)}</em></div>")
    body.append("<ul>")
    summary_labels = {
        "project": "项目",
        "config_path": "配置路径",
        "num_items": "样例数",
        "pass_rate": "通过率",
        "report_url": "报告链接",
    }
    for k in ["project", "config_path", "num_items", "pass_rate", "report_url"]:
        if k in summary:
            label = summary_labels.get(k, k)
            body.append(f"<li><b>{escape(label)}</b>：{escape(str(summary[k]))}</li>")
    body.append("</ul>")
    if "rows" in summary:
        body.append("<h2>明细</h2><ol>")
        for r in summary["rows"][:100]:
            body.append("<li>")
            body.append(f"<div><b>问：</b> {escape(str(r.get('question','')[:200]))}</div>")
            body.append(f"<div><b>答：</b> {escape(str(r.get('answer','')[:200]))}</div>")
            j = r.get("judge", {})
            body.append(
                f"<div><b>评判：</b> {escape(str(j.get('decision','?')))} "
                f"(正确性={escape(str(j.get('correctness','?')))} 依据性={escape(str(j.get('grounding','?')))})</div>"
            )
            rationale = j.get("rationale")
            if rationale:
                body.append(
                    f"<div><b>理由：</b> {escape(str(rationale)[:300])}</div>"
                )
            body.append("</li>")
        body.append("</ol>")
    html = head + "\n" + "\n".join(body) + "\n" + tail
    p.write_text(html, encoding="utf-8")
