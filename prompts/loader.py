from __future__ import annotations

import os
from functools import lru_cache


_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_PROMPTS_DIR = os.path.join(_ROOT, "prompts")


@lru_cache(maxsize=128)
def load_prompt(rel_path: str) -> str:
    """从 prompts 目录加载提示词文件。

    rel_path：相对于 prompts/ 目录的路径，例如 "system/assistant.md"。
    以 UTF-8 字符串返回文件内容。若文件不存在则抛出 FileNotFoundError。
    """
    path = os.path.join(_PROMPTS_DIR, rel_path)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
