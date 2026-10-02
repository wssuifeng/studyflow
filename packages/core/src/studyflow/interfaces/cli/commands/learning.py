from __future__ import annotations
from pathlib import Path
import typer
from .. import runtime
from ..runtime import output, fail
from ..registry import submission_app


@submission_app.command("get")
def submission_get(submission_id: str = typer.Option(..., "--id"), format: str = typer.Option("text", "--format")) -> None:
    try:
        output({"ok": True, "submission": runtime.service().submission_detail(submission_id)}, format)
    except Exception as exc:
        fail(exc)

@submission_app.command("list-pending")
def submission_pending(format: str = typer.Option("text", "--format")) -> None:
    try:
        queue = runtime.service().agent_queue()
        output({"ok": True, "submissions": queue["waiting_review"], "queue": queue}, format)
    except Exception as exc:
        fail(exc)

@submission_app.command("revise")
def submission_revise(parent_submission: str = typer.Option(..., "--parent"), answer_file: Path = typer.Option(..., "--file", exists=True, readable=True), idempotency_key: str | None = typer.Option(None, "--idempotency-key"), format: str = typer.Option("text", "--format")) -> None:
    """基于需要修正的作答创建不可覆盖的修正版。"""
    try:
        submission = runtime.service().revise_submission(parent_submission, answer_file.read_text(encoding="utf-8"), idempotency_key=idempotency_key, source="AGENT_CLI")
        output({"ok": True, "submission_id": submission.id, "parent_submission_id": submission.parent_submission_id, "attempt_number": submission.attempt_number, "attempt_kind": submission.attempt_kind, "status": submission.status, "source": submission.source, "next_action": submission.next_action}, format)
    except Exception as exc:
        fail(exc)

@submission_app.command("retest")
def submission_retest(parent_submission: str = typer.Option(..., "--parent"), answer_file: Path = typer.Option(..., "--file", exists=True, readable=True), idempotency_key: str | None = typer.Option(None, "--idempotency-key"), format: str = typer.Option("text", "--format")) -> None:
    """基于要求复测的作答创建不可覆盖的复测版。"""
    try:
        submission = runtime.service().retest_submission(parent_submission, answer_file.read_text(encoding="utf-8"), idempotency_key=idempotency_key, source="AGENT_CLI")
        output({"ok": True, "submission_id": submission.id, "parent_submission_id": submission.parent_submission_id, "attempt_number": submission.attempt_number, "attempt_kind": submission.attempt_kind, "status": submission.status, "source": submission.source, "next_action": submission.next_action}, format)
    except Exception as exc:
        fail(exc)
