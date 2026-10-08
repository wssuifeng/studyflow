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


@plan_app.command("notebook-get")
def notebook_get(plan_id: str = typer.Option(...,"--id"), format: str = typer.Option("text","--format")):
    try: output({"ok":True, **runtime.service().plan_notebook(plan_id)}, format)
    except Exception as exc: fail(exc)


@plan_app.command("notebook-save")
def notebook_save(plan_id: str = typer.Option(...,"--id"), file: str = typer.Option(...,"--file"), expected_version: int = typer.Option(...,"--expected-version"), idempotency_key: str = typer.Option(...,"--idempotency-key"), format: str = typer.Option("text","--format")):
    try:
        import json
        from studyflow.infrastructure.markdown import safe_resolve
        from studyflow.shared.domain import DomainError
        service=runtime.service(); path=safe_resolve(service.settings.workspace_root,file)
        if path.suffix.lower()!=".json": raise DomainError("UNSUPPORTED_DOCUMENT_TYPE","笔记CLI输入需要JSON文件。")
        if not path.is_file(): raise DomainError("DOCUMENT_NOT_FOUND","笔记输入文件不存在。")
        if path.stat().st_size>5_000_000: raise DomainError("INVALID_ARGUMENT","笔记输入文件过大。")
        try: payload=json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, ValueError) as exc: raise DomainError("INVALID_ARGUMENT","笔记输入不是有效UTF-8 JSON。") from exc
        blocks=payload.get("blocks") if isinstance(payload,dict) else payload
        output({"ok":True, **service.save_plan_notebook(plan_id,blocks,expected_version,idempotency_key,source="AGENT_CLI")},format)
    except Exception as exc: fail(exc)
