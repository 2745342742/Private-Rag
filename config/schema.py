from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from prompts.loader import load_prompt
import yaml


def _resolve_prompt_references(data: Any) -> Any:
    if isinstance(data, dict):
        if "prompt_file" in data:
            path = data.pop("prompt_file")
            if path:
                data["content"] = load_prompt(str(path))
        for key, value in list(data.items()):
            data[key] = _resolve_prompt_references(value)
        return data
    if isinstance(data, list):
        return [_resolve_prompt_references(item) for item in data]
    return data


class EnvConfig(BaseModel):
    openai_api_key: Optional[str] = None
    openai_organization: Optional[str] = None
    openai_project: Optional[str] = None
    # OpenAI 兼容网关（如阿里云百炼）：https://dashscope.aliyuncs.com/compatible-mode/v1
    openai_base_url: Optional[str] = None


class DataConfig(BaseModel):
    """语料路径仅供 evals 自动出题等可选能力；平台入库走用户上传，默认空。"""

    paths: List[str] = Field(default_factory=list)
    include_extensions: List[str] = Field(
        default_factory=lambda: [
            ".pdf",
            ".md",
            ".html",
            ".txt",
            ".docx",
            ".csv",
            ".xml",
        ]
    )
    exclude_globs: List[str] = Field(
        default_factory=lambda: [
            "**/node_modules/**",
            "**/.git/**",
        ]
    )


class ChunkingConfig(BaseModel):
    """实际入库由 rag_lc 使用 RecursiveCharacterTextSplitter；
    strategy 仅作配置标注，target_token_range / overlap_tokens 生效。
    """

    model_config = ConfigDict(extra="ignore")

    strategy: str = "recursive"
    target_token_range: Tuple[int, int] = (300, 700)
    overlap_tokens: int = 60


class EmbeddingsConfig(BaseModel):
    provider: Literal["openai"] = "openai"
    model: str = "text-embedding-3-large"
    batch_size: int = 10
    # 百炼 text-embedding-v3/v4 等支持自定义维度；不填则用服务商默认值
    dimensions: Optional[int] = None


class QdrantConfig(BaseModel):
    url: str = "http://localhost:6333"
    api_key: Optional[str] = None
    collection: str
    distance: Literal["cosine", "dot", "euclid"] = "cosine"
    ef: int = 128
    m: int = 64


class CustomVectorStoreConfig(BaseModel):
    kind: Literal["qdrant"] = "qdrant"
    qdrant: Optional[QdrantConfig] = None


class VectorStoreConfig(BaseModel):
    backend: Literal["custom"] = "custom"
    custom: Optional[CustomVectorStoreConfig] = None

    @model_validator(mode="after")
    def _validate_backend(self) -> "VectorStoreConfig":
        if not self.custom:
            raise ValueError("必须提供 vector_store.custom")
        if self.custom.kind == "qdrant" and not self.custom.qdrant:
            raise ValueError("当 kind == qdrant 时，必须提供 vector_store.custom.qdrant")
        return self


class CitationsConfig(BaseModel):
    include_spans: bool = True
    max_per_source: int = 3


class QueryConfig(BaseModel):
    """检索参数。混合检索（稠密 + BM25 + RRF）在 rag_lc 中实现，无扩写/HyDE/重排。"""

    model_config = ConfigDict(extra="ignore")

    top_k: int = 8
    filters: Dict[str, Any] = Field(default_factory=dict)
    max_context_tokens: int = 4000
    citations: CitationsConfig = Field(default_factory=CitationsConfig)


def _default_system_prompt() -> str:
    try:
        return load_prompt("system/assistant.md")
    except Exception:
        return (
            "你是一个基于上下文的 grounded 企业助手。严格根据提供的上下文作答。\n"
            "若信息不足，请提出澄清问题。始终引用来源的文件和页码。"
        )


class SynthesisConfig(BaseModel):
    model: str = "gpt-5"
    system_prompt: str = Field(default_factory=_default_system_prompt)
    structured_outputs: bool = True
    reasoning_effort: Literal["low", "medium", "high"] = "low"


class JudgeConfig(BaseModel):
    model: str = "gpt-5-mini"
    style: Literal["single"] = "single"
    rubric: Literal["qa_grounded"] = "qa_grounded"
    structured_outputs: bool = True


class ThresholdsConfig(BaseModel):
    pass_rate: float = 0.75
    grounding_min: float = 0.8


class AutoEvalsConfig(BaseModel):
    items_target: int = 150
    mix: Dict[Literal["easy", "medium", "hard"], float] = Field(
        default_factory=lambda: {"easy": 0.5, "medium": 0.35, "hard": 0.15}
    )
    per_tag_cap: int = 30
    per_source_cap: Optional[int] = None
    exclude_patterns: List[str] = Field(
        default_factory=lambda: ["confidential", "legal_hold"]
    )
    scan_docs: Optional[int] = None
    qgen_workers: int = 8
    quality_regen_limit: int = 100
    questions_per_context: int = 3
    context_chars_min: int = 1200
    context_chars_max: int = 2400
    per_doc_context_cap: int = 10


class EvalsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: Literal["user", "auto"] = "user"
    dataset_path: Optional[str] = None
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    auto: AutoEvalsConfig = Field(default_factory=AutoEvalsConfig)
    # 向后兼容
    judge_model: Optional[str] = None

    @model_validator(mode="after")
    def _coerce_legacy(self) -> "EvalsConfig":
        if self.judge_model and (
            not self.judge or self.judge.model == JudgeConfig().model
        ):
            self.judge.model = self.judge_model
        return self


class RootConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project: str
    env: EnvConfig = Field(default_factory=EnvConfig)
    data: DataConfig
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    query: QueryConfig = Field(default_factory=QueryConfig)
    synthesis: SynthesisConfig = Field(default_factory=SynthesisConfig)
    evals: EvalsConfig = Field(default_factory=EvalsConfig)


def load_config(path: str) -> RootConfig:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg = _resolve_prompt_references(cfg)
    try:
        return RootConfig(**cfg)
    except ValidationError as e:
        raise SystemExit(f"无效配置：{e}")


def lint_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    resolved = _resolve_prompt_references(raw)
    normalized = RootConfig(**resolved).model_dump()
    unused = set(raw.keys()) - set(normalized.keys())
    return {"normalized": normalized, "unused_top_level_keys": sorted(list(unused))}
