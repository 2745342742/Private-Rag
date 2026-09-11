from prompts.loader import load_prompt


def _fallback_single() -> str:
    return (
        "你是一名严格的评估评判员。\n"
        "判断 model_answer 是否在语义上与 correct_answer 匹配，且完全被 citation_text 支持。\n"
        "对任何无依据的陈述或幻觉予以扣分。忽略轻微的格式或措辞差异。\n"
        "返回紧凑 JSON 对象，包含键：decision (pass|fail)、correctness (0..1)、grounding (0..1)、rationale。"
    )


try:
    SINGLE_RUBRIC_QA_GROUNDED = load_prompt("evals/judge_single.md")
except Exception:
    SINGLE_RUBRIC_QA_GROUNDED = _fallback_single()
