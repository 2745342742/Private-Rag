from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth, db

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "display_name": row.get("display_name"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


@router.post("/register")
def register(body: RegisterRequest) -> dict[str, Any]:
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    password_hash = auth.hash_password(body.password)
    try:
        with db.get_conn() as conn:
            row = db.fetchone(
                conn,
                """
                INSERT INTO users (username, password_hash, display_name)
                VALUES (%s, %s, %s)
                RETURNING id, username, display_name, created_at
                """,
                (username, password_hash, body.display_name),
            )
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(status_code=409, detail="用户名已存在") from exc
        raise
    assert row is not None
    token, expires_in = auth.create_access_token(
        user_id=str(row["id"]), username=row["username"]
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": _public_user(row),
    }


@router.post("/login")
def login(body: LoginRequest) -> dict[str, Any]:
    with db.get_conn() as conn:
        row = db.fetchone(
            conn,
            """
            SELECT id, username, display_name, password_hash, created_at
            FROM users WHERE username = %s
            """,
            (body.username.strip(),),
        )
    if not row or not auth.verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token, expires_in = auth.create_access_token(
        user_id=str(row["id"]), username=row["username"]
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": _public_user(row),
    }


@router.get("/me")
def me(user: dict[str, Any] = Depends(auth.get_current_user)) -> dict[str, Any]:
    return {"user": user}
