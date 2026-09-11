import os
from typing import Any, Optional, Dict

from openai import OpenAI
from dotenv import load_dotenv, find_dotenv

from config.schema import RootConfig


def _ensure_dotenv_precedence() -> None:
    """加载 .env，并使其优先于已导出的环境变量。

    我们希望 .env 文件中定义的值覆盖已导出的环境变量
    OPENAI_API_KEY、OPENAI_ORG_ID 和 OPENAI_PROJECT_ID。使用
    load_dotenv 并设置 override=True 可实现此行为。若不存在 .env，
    则为无操作。
    """
    try:
        # 从当前工作目录查找最近的 .env；若未找到，load_dotenv 将无操作
        env_path = find_dotenv(usecwd=True)
        if env_path:
            load_dotenv(env_path, override=True)
        else:
            load_dotenv(override=True)
    except Exception:
        # 尽力加载；若 dotenv 不可用或发生错误则忽略
        pass


def resolve_env_placeholder(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return (
            None
            if value
            in (
                None,
                "",
            )
            else value
        )
    if value.startswith("${") and value.endswith("}"):
        env_name = value[2:-1]
        return os.getenv(env_name)
    return value


def resolve_openai_base_url(cfg: Optional[RootConfig] = None) -> Optional[str]:
    """解析 OpenAI 兼容 API 的 base_url（百炼等）。"""
    _ensure_dotenv_precedence()
    from_cfg = None
    if cfg is not None:
        from_cfg = resolve_env_placeholder(
            getattr(getattr(cfg, "env", None), "openai_base_url", None)
        )
    return from_cfg or os.getenv("OPENAI_BASE_URL") or None


def uses_chat_completions_api(cfg: Optional[RootConfig] = None) -> bool:
    """是否应使用 Chat Completions 而非 OpenAI Responses API。

    阿里云百炼等兼容网关通常只稳定支持 chat.completions / embeddings。
    可通过 OPENAI_API_MODE=responses|chat 强制覆盖。
    """
    mode = (os.getenv("OPENAI_API_MODE") or "").strip().lower()
    if mode in {"chat", "chat_completions", "completions"}:
        return True
    if mode in {"responses", "response"}:
        return False
    base_url = resolve_openai_base_url(cfg)
    if base_url:
        lowered = base_url.rstrip("/").lower()
        # 官方 OpenAI 主机继续走 Responses；其余兼容网关默认走 Chat Completions
        if "api.openai.com" not in lowered:
            return True
        return False
    rag_cfg = (os.getenv("RAG_CONFIG") or "").replace("\\", "/").lower()
    if "china" in rag_cfg or "bailian" in rag_cfg:
        return True
    if cfg is not None:
        project = str(getattr(cfg, "project", "") or "").lower()
        if "bailian" in project or "china" in project:
            return True
    return False


def build_openai_client(cfg: RootConfig) -> OpenAI:
    # 确保 .env 中的值优先于已导出的环境变量
    _ensure_dotenv_precedence()

    api_key = resolve_env_placeholder(cfg.env.openai_api_key) or os.getenv(
        "OPENAI_API_KEY"
    )
    if not api_key:
        raise RuntimeError(
            "需要提供 OPENAI_API_KEY（可为阿里云百炼等兼容平台的 API Key）"
        )
    organization = resolve_env_placeholder(
        getattr(cfg.env, "openai_organization", None)
    ) or os.getenv("OPENAI_ORG_ID")
    project = resolve_env_placeholder(
        getattr(cfg.env, "openai_project", None)
    ) or os.getenv("OPENAI_PROJECT_ID")
    base_url = resolve_openai_base_url(cfg)

    kwargs: Dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    if organization:
        kwargs["organization"] = organization
    if project:
        kwargs["project"] = project
    return OpenAI(**kwargs)


def embedding_create_kwargs(cfg: RootConfig, *, model: str, input: Any) -> Dict[str, Any]:
    """构建 embeddings.create 参数，附带可选 dimensions。"""
    kwargs: Dict[str, Any] = {"model": model, "input": input}
    dims = getattr(getattr(cfg, "embeddings", None), "dimensions", None)
    if dims:
        kwargs["dimensions"] = int(dims)
    return kwargs
