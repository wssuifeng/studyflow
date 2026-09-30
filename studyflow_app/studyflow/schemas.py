from __future__ import annotations

from pydantic import BaseModel, Field

class SubmissionInput(BaseModel):
    exercise_id: str
    task_id: str | None = None
    answer_text: str = Field(min_length=1)
    idempotency_key: str | None = None

class ReviewInput(BaseModel):
    submission_id: str
    summary: str = Field(min_length=1)
    detail_markdown: str = ""
    issue_count: int = Field(default=0, ge=0)
    needs_revision: bool = False
    idempotency_key: str | None = None
