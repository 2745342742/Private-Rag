from prompts.loader import load_prompt


def _fallback_single() -> str:
    return (
        "你是一名严格的评估评判员。\n"
        "任务：对比 model_answer、correct_answer（参考答案）、citation_text（检索原文）。\n"
        "1. correctness：判断model_answer核心答案语义是否和correct_answer一致。"
        "允许转述、总结、基于原文的合理推导，句式差异不扣分。\n"
        "2. grounding（有据性）：判断model_answer中**所有事实陈述**是否都来自citation_text。\n"
        " 允许：基于原文给出信息做的合理归纳、解释；\n"
        " 禁止：文档不存在的虚构事实、编造参数、编造结论，这类才算幻觉，予以扣分。\n"
        "忽略轻微的格式或措辞差异。\n"
        "只输出一个 JSON 对象，不要 markdown 代码块，不要前后说明。\n"
        '键：decision("pass"|"fail")、correctness(0..1)、grounding(0..1)、rationale(字符串)。\n'
        '示例：{"decision":"pass","correctness":1.0,"grounding":0.9,"rationale":"与标准答案一致且有原文依据。"}'
    )


try:
    SINGLE_RUBRIC_QA_GROUNDED = load_prompt("evals/judge_single.md")
except Exception:
    SINGLE_RUBRIC_QA_GROUNDED = _fallback_single()
