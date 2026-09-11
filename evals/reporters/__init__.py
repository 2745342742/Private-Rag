from __future__ import annotations

# 为向后兼容重新导出常用报告器
from .md import write_markdown_report  # noqa: F401
from .html import write_html_report  # noqa: F401
