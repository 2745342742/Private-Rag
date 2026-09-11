from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import db


_bearer = HTTPBearer(auto_error=False)


def jwt_secret() -> str:
    return os.getenv("JWT_SECRET") or "dev-only-change-me"


def jwt_expire_hours() -> int:
    try:
        return max(1, int(os.getenv("JWT_EXPIRE_HOURS") or "72"))
    except ValueError:
        return 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def create_access_token(*, user_id: str, username: str) -> tuple[str, int]:
    expires_in = jwt_expire_hours() * 3600
    payload = {
        "sub": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, jwt_secret(), algorithm="HS256")
    return token, expires_in


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的登录凭证",
        ) from exc


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    payload = decode_token(creds.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="无效登录凭证")
    with db.get_conn() as conn:
        user = db.fetchone(
            conn,
            "SELECT id, username, display_name, created_at FROM users WHERE id = %s",
            (user_id,),
        )
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "display_name": user.get("display_name"),
        "created_at": user["created_at"].isoformat() if user.get("created_at") else None,
    }


def ensure_uuid(value: str, *, field: str = "id") -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field}") from exc
