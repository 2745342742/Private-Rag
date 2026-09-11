from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

try:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except Exception:
    pass

from .platform import api_router, init_db  # noqa: E402

app = FastAPI(title="个人知识库 API")


def _parse_cors_allow_origins(value: str | None) -> list[str]:
    if not value:
        return []
    return [origin.strip() for origin in value.split(",") if origin.strip()]


cors_allow_origins = _parse_cors_allow_origins(
    os.getenv("KNOWLEDGE_CORS_ALLOW_ORIGINS")
) or [
    "http://localhost:5172",
    "http://127.0.0.1:5172",
]

if cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "Authorization"],
        expose_headers=["Content-Disposition"],
    )


@app.on_event("startup")
def _platform_startup() -> None:
    if os.getenv("DATABASE_URL"):
        try:
            init_db()
        except Exception as exc:  # noqa: BLE001
            print(f"[platform] 数据库初始化失败：{exc}")


app.include_router(api_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}
