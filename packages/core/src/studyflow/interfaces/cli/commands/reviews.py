from __future__ import annotations
from pathlib import Path
import typer
from .. import runtime
from ..runtime import output, fail
from ..registry import review_app, assignment_app


@assignment_app.command("queue")
def assignment_queue(plan_line_id: str | None = typer.Option(None, "--plan-line"), format: str = typer.Option("text", "--format"), full:bool=typer.Option(False,"--full"), role:str=typer.Option("agent","--role"), limit:int=typer.Option(50,"--limit")) -> None:
    """列出等待批改、修正或复测的统一 Agent 队列。"""
    try:
        service=runtime.service()
        if full:output({"ok": True, **service.agent_queue(plan_line_id)},format)
        else:
            from studyflow.modules.reviews.queue_queries import summary
            output({"ok":True,**summary(service.reviews,role=role,plan_line_id=plan_line_id,limit=limit)},format)
    except Exception as exc:
        fail(exc)

@review_app.command("write")
def review_write(submission_id: str = typer.Option(..., "--submission"), summary: str = typer.Option(..., "--summary"), detail_file: Path | None = typer.Option(None, "--file"), issue_count: int = typer.Option(0, "--issue-count"), needs_revision: bool = typer.Option(False, "--needs-revision"), decision: str | None = typer.Option(None, "--decision", help="PASSED / REVISION_REQUIRED / RETEST_REQUIRED"), next_action: str = typer.Option("", "--next-action"), idempotency_key: str | None = typer.Option(None, "--idempotency-key"), format: str = typer.Option("text", "--format")) -> None:
    try:
        detail = detail_file.read_text(encoding="utf-8") if detail_file else ""
        review = runtime.service().write_review(submission_id, summary, detail, issue_count, needs_revision, idempotency_key, decision=decision, next_action=next_action)
        output({"ok": True, "review_id": review.id, "submission_id": review.submission_id, "decision": review.decision, "next_action": review.next_action, "needs_revision": review.needs_revision}, format)
    except Exception as exc:
        fail(exc)
