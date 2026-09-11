from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from typing import Literal


class JudgeDecision(BaseModel):
    decision: Literal["pass", "fail"]
    correctness: float = Field(ge=0, le=1)
    grounding: float = Field(ge=0, le=1)
    rationale: str

    @field_validator("rationale")
    @classmethod
    def _trim(cls, v: str) -> str:
        return (v or "").strip()
