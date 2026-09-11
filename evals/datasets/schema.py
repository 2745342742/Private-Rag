from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field, ValidationError
import json


class EvalItem(BaseModel):
    id: Optional[str] = None
    question: str
    citation_text: str
    correct_answer: str
    source_id: Optional[str] = None
    page: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    difficulty: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class EvalRow(BaseModel):
    item: EvalItem


def load_and_validate_jsonl(path: str | Path) -> List[EvalRow]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"未找到数据集：{p}")
    rows: List[EvalRow] = []
    with p.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception as e:
                raise ValueError(f"第 {i} 行 JSON 无效：{e}")

            # 允许旧版/扁平行，强制转换为 {"item": {...}} 形状。
            if not isinstance(obj, dict):
                raise ValueError(
                    f"第 {i} 行 JSON 对象无效：期望 dict，得到 {type(obj)}"
                )

            try:
                rows.append(EvalRow(**obj))
            except ValidationError as e:
                raise ValueError(f"第 {i} 行 schema 错误：{e}")
    if not rows:
        raise ValueError("解析后数据集为空")
    return rows


def write_jsonl(rows: Iterable[EvalRow | Dict[str, Any]], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            if isinstance(r, EvalRow):
                data = r.model_dump()
            else:
                data = r
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
