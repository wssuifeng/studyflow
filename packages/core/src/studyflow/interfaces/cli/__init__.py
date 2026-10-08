"""CLI assembly; command and output contracts remain unchanged."""
from .runtime import app
from .commands import system, planning, courses, learning, reviews, documents, workspace, api

__all__ = ["app"]
