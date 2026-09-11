from __future__ import annotations

from fastapi import APIRouter

from .routes_auth import router as auth_router
from .routes_chat import router as chat_router
from .routes_docs import router as docs_router
from .routes_eval import router as eval_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(chat_router)
api_router.include_router(docs_router)
api_router.include_router(eval_router)


@api_router.get("/health")
def platform_health() -> dict[str, str]:
    return {"status": "ok"}
