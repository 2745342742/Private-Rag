"""YAML 配置 schema 与环境变量工具（原 cli 共享模块，已无 CLI 入口）。"""

from .schema import (
    RootConfig,
    load_config,
    lint_config,
)

__all__ = [
    "RootConfig",
    "load_config",
    "lint_config",
]
