from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from config.env_utils import build_openai_client, uses_chat_completions_api
from config.schema import RootConfig
from prompts.loader import load_prompt


def _extract_output_text(resp: Any) -> str:
    text = getattr(resp, "output_text", None)
    if text is not None:
        return text
    text_out = ""
    try:
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", "") == "message":
                for block in getattr(item, "content", []) or []:
                    btype = getattr(block, "type", "")
                    if btype in ("output_text", "text"):
                        piece = getattr(block, "text", None) or getattr(
                            block, "value", None
                        )
                        if piece:
                            text_out += piece
    except Exception:
        pass
    return text_out


def _json_loads_safe(s: str) -> Any:
    import re

    t = (s or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE)
    last_brace = max(t.rfind("}"), t.rfind("]"))
    if last_brace != -1:
        t = t[: last_brace + 1]
    return json.loads(t)


def _chat_json(client: Any, cfg: RootConfig, system: str, user: str) -> str:
    if uses_chat_completions_api(cfg):
        resp = client.chat.completions.create(
            model=cfg.synthesis.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "") if resp.choices else ""
    resp = client.responses.create(
        model=cfg.synthesis.model,
        input=[
            {"role": "developer", "content": system},
            {"role": "user", "content": user},
        ],
        store=False,
    )
    return _extract_output_text(resp)


try:
    SYS_PROMPT = load_prompt("evals/qgen_single.md")
except Exception:
    SYS_PROMPT = (
        "根据给定材料生成 1 道可从材料直接回答的评测题。"
        "输出 JSON：{\"questions\":[{\"question\",\"correct_answer\",\"difficulty\",\"tags\"}]}"
    )

try:
    SYS_PROMPT_CONTEXT = load_prompt("evals/qgen_many.md")
except Exception:
    SYS_PROMPT_CONTEXT = (
        "根据给定上下文生成多道高质量、可严格依据上下文回答的评测题。"
        "输出 JSON：{\"questions\":[{\"question\",\"correct_answer\",\"difficulty\",\"tags\"}]}"
    )


def generate_one(
    cfg: RootConfig,
    span: Dict[str, Any],
    difficulty: str = "easy",
    client: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    try:
        client = client or build_openai_client(cfg)
        payload = {
            "span": span.get("text", ""),
            "hint_tags": span.get("tags", []),
            "difficulty": difficulty,
        }
        text = _chat_json(client, cfg, SYS_PROMPT, json.dumps(payload, ensure_ascii=False))
        data = _json_loads_safe(text)
        if isinstance(data, dict) and isinstance(data.get("questions"), list):
            items = data["questions"]
            data = items[0] if items else {}
        elif isinstance(data, list):
            data = data[0] if data else {}
        return {
            "question": data.get("question", ""),
            "correct_answer": data.get("correct_answer", ""),
            "citation_text": span.get("text", ""),
            "source_id": span.get("source_id"),
            "page": span.get("page"),
            "char_start": span.get("char_start"),
            "char_end": span.get("char_end"),
            "difficulty": data.get("difficulty", difficulty),
            "tags": span.get("tags", []),
        }
    except Exception:
        return None


def generate_many_from_context(
    cfg: RootConfig,
    context: Dict[str, Any],
    n_questions: int = 3,
    style_hints: Optional[List[str]] = None,
    client: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    try:
        client = client or build_openai_client(cfg)
        payload = {
            "context": context.get("text", ""),
            "request": {
                "count": int(max(1, n_questions)),
                "style_hints": style_hints
                or [
                    "definition",
                    "procedure",
                    "numeric",
                    "comparison",
                    "why",
                    "edge_case",
                ],
            },
        }
        text = _chat_json(
            client, cfg, SYS_PROMPT_CONTEXT, json.dumps(payload, ensure_ascii=False)
        )
        data = _json_loads_safe(text)
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                data = data["items"]
            elif isinstance(data.get("questions"), list):
                data = data["questions"]
        if not isinstance(data, list):
            return []
        rows: List[Dict[str, Any]] = []
        for obj in data:
            if not isinstance(obj, dict):
                continue
            q = (obj.get("question") or "").strip()
            a = (obj.get("correct_answer") or "").strip()
            if not q or not a:
                continue
            rows.append(
                {
                    "question": q,
                    "correct_answer": a,
                    "citation_text": context.get("text", ""),
                    "source_id": context.get("source_id") or context.get("doc_id"),
                    "page": context.get("page"),
                    "char_start": context.get("char_start"),
                    "char_end": context.get("char_end"),
                    "difficulty": (obj.get("difficulty") or "").lower() or None,
                    "tags": obj.get("tags") or context.get("tags") or [],
                }
            )
        return rows
    except Exception:
        return []


def generate_questions(
    cfg: RootConfig,
    spans: List[Dict[str, Any]],
    difficulty: str = "easy",
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for sp in spans:
        row = generate_one(cfg, sp, difficulty)
        if row:
            out.append(row)
    return out
