from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewInput(BaseModel):
    submission_id: str
    summary: str = Field(min_length=1)
    detail_markdown: str = ""
    issue_count: int = Field(default=0, ge=0)
    needs_revision: bool = False
    idempotency_key: str | None = None
