from __future__ import annotations

from pydantic import BaseModel, Field


class SubmissionInput(BaseModel):
    exercise_id: str
    task_id: str | None = None
    answer_text: str = Field(min_length=1)
    idempotency_key: str | None = None
