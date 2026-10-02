"""Compatibility DTO imports; each contract is owned by its business module."""
from studyflow.modules.learning.schemas import SubmissionInput
from studyflow.modules.reviews.schemas import ReviewInput

__all__ = ["SubmissionInput", "ReviewInput"]
