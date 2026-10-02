from __future__ import annotations
from datetime import date
import typer
from .. import runtime
from ..runtime import output, fail
from ..registry import plan_app, task_app


@plan_app.command("list")
def plan_list(format: str = typer.Option("text", "--format")) -> None:
    try:
        rows = runtime.service().list_plan_lines()
        output({"ok": True, "plans": [{"id": row.id, "name": row.name, "priority": row.priority, "status": row.status} for row in rows]}, format)
    except Exception as exc:
        fail(exc)

@plan_app.command("create")
def plan_create(name: str = typer.Option(..., "--name"), priority: int = typer.Option(1, "--priority"), format: str = typer.Option("text", "--format")) -> None:
    try:
        row = runtime.service().create_plan_line(name, priority)
        output({"ok": True, "id": row.id, "name": row.name, "priority": row.priority, "status": row.status}, format)
    except Exception as exc:
        fail(exc)

def _task_list(date_value: str | None, plan_line_id: str | None, task_kind: str | None, format: str) -> None:
    try:
        target = date.fromisoformat(date_value) if date_value else None
        rows = runtime.service().list_tasks(target, plan_line_id, task_kind)
        output({"ok": True, "tasks": [{"id": row.id, "title": row.title, "date": row.scheduled_date, "status": row.status, "kind": row.task_kind, "plan_line": row.plan_line.name if row.plan_line else None} for row in rows]}, format)
    except Exception as exc:
        fail(exc)

@plan_app.command("task-list")
def plan_task_list(date_value: str | None = typer.Option(None, "--date"), plan_line_id: str | None = typer.Option(None, "--plan-line"), task_kind: str | None = typer.Option(None, "--kind"), format: str = typer.Option("text", "--format")) -> None:
    _task_list(date_value, plan_line_id, task_kind, format)

@task_app.command("list")
def task_list(date_value: str | None = typer.Option(None, "--date"), plan_line_id: str | None = typer.Option(None, "--plan-line"), task_kind: str | None = typer.Option(None, "--kind"), format: str = typer.Option("text", "--format")) -> None:
    _task_list(date_value, plan_line_id, task_kind, format)

def _task_create(title: str, date_value: str, task_kind: str, plan_line_id: str | None, description: str, priority: int, format: str) -> None:
    try:
        row = runtime.service().create_task(title, date.fromisoformat(date_value), task_kind, description, plan_line_id=plan_line_id, priority=priority)
        output({"ok": True, "id": row.id, "title": row.title, "date": row.scheduled_date, "kind": row.task_kind, "plan_line_id": row.plan_line_id}, format)
    except Exception as exc:
        fail(exc)

@plan_app.command("task-create")
def plan_task_create(title: str = typer.Option(..., "--title"), date_value: str = typer.Option(..., "--date"), task_kind: str = typer.Option("OTHER", "--kind"), plan_line_id: str | None = typer.Option(None, "--plan-line"), description: str = typer.Option("", "--description"), priority: int = typer.Option(1, "--priority"), format: str = typer.Option("text", "--format")) -> None:
    _task_create(title, date_value, task_kind, plan_line_id, description, priority, format)

@task_app.command("create")
def task_create(title: str = typer.Option(..., "--title"), date_value: str = typer.Option(..., "--date"), task_kind: str = typer.Option("OTHER", "--kind"), plan_line_id: str | None = typer.Option(None, "--plan-line"), description: str = typer.Option("", "--description"), priority: int = typer.Option(1, "--priority"), format: str = typer.Option("text", "--format")) -> None:
    _task_create(title, date_value, task_kind, plan_line_id, description, priority, format)

@plan_app.command("detail")
def plan_detail(plan_id: str = typer.Option(..., "--id"), format: str = typer.Option("text", "--format")) -> None:
    try:
        output({"ok": True, **runtime.service().plan_detail(plan_id)}, format)
    except Exception as exc:
        fail(exc)
