from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from .config import Settings
from .db import build_engine, build_session_factory, init_db
from .domain import DomainError
from .diagnostics import record_engine_error
from .engine_protocol import CAPABILITIES, PROTOCOL_VERSION, capabilities_payload, error_payload, make_response, version_payload
from .services import AppService
from .presentation import course_summary, submission_summary


class StudyFlowEngine:
    """stdin/stdout JSON-RPC adapter over the shared AppService.

    stdout is reserved for one JSON response per input line. Diagnostics belong on stderr.
    """

    def __init__(self, settings: Settings | None = None, service: AppService | None = None):
        self.settings = settings or (service.settings if service else Settings.from_env())
        self.settings.ensure_layout()
        self.engine = None
        if service is None:
            self.engine = build_engine(self.settings)
            init_db(self.engine)
            service = AppService(self.settings, build_session_factory(self.engine))
        self.service = service

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            if not isinstance(request, dict):
                raise DomainError("INVALID_REQUEST", "请求必须是 JSON 对象。", "使用 {id, method, params} 对象。")
            method = request.get("method")
            if not isinstance(method, str) or not method.strip():
                raise DomainError("INVALID_REQUEST", "请求缺少 method。", "传入有效方法名。")
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise DomainError("INVALID_REQUEST", "params 必须是 JSON 对象。", "使用键值对象。")
            data = self._dispatch(method.strip(), params)
            return make_response(request_id, data=data)
        except Exception as exc:
            error = error_payload(exc)
            if not isinstance(exc, DomainError):
                diagnostic = record_engine_error(self.settings.log_root, exc)
                error.update(diagnostic)
                error["next_action"] = "打开工作区 .studyflow/logs 中的 Engine 错误日志，并提供 diagnostic_id；答案已保留，重试请使用原幂等键。"
            return make_response(request_id, error=error)

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "system.version":
            return version_payload(self.settings)
        if method == "system.capabilities":
            return capabilities_payload(self.settings)
        if method == "system.doctor":
            return self._doctor()
        if method in {"study.today", "study.status"}:
            return self._today(params)
        if method == "assignment.queue":
            return {"protocol_version": PROTOCOL_VERSION, **self.service.agent_queue(params.get("plan_line_id"))}
        if method == "plan.list":
            rows = self.service.list_plan_lines(bool(params.get("include_inactive", False)))
            return {"protocol_version": PROTOCOL_VERSION, "plans": [self._plan(row) for row in rows]}
        if method == "plan.detail":
            try:
                target = date.fromisoformat(str(params["date"])) if params.get("date") else None
            except ValueError as exc:
                raise DomainError("INVALID_ARGUMENT", "date 必须使用 YYYY-MM-DD 格式。", "传入有效 ISO 日期。") from exc
            return {"protocol_version": PROTOCOL_VERSION, **self.service.plan_detail(self._required_string(params, "plan_line_id"), target)}
        if method == "course.list":
            rows = self.service.list_courses(params.get("plan_line_id"))
            return {"protocol_version": PROTOCOL_VERSION, "courses": [self._course(row) for row in rows]}
        if method == "course.detail":
            return {"protocol_version": PROTOCOL_VERSION, **self.service.course_detail(self._required_string(params, "course_id"))}
        if method == "course.answers.get":
            return {"protocol_version": PROTOCOL_VERSION, **self.service.course_answer_sheet(self._required_string(params, "course_id"))}
        if method in {"course.answers.draft.save", "course.answers.submit"}:
            result = self.service.write_course_answers(
                self._required_string(params, "course_id"), params.get("answers"),
                "DRAFT_SAVE" if method.endswith("draft.save") else "SUBMIT",
                params.get("idempotency_key"), source=params.get("source", "USER_WEB"))
            return {"protocol_version": PROTOCOL_VERSION, **result}
        if method == "document.read":
            return {"protocol_version": PROTOCOL_VERSION, **self.service.read_document(self._required_string(params, "path"), render=bool(params.get("render", True)))}
        if method == "submission.get":
            return {"protocol_version": PROTOCOL_VERSION, **self.service.submission_detail(self._required_string(params, "submission_id"))}
        if method == "submission.draft.save":
            exercise_id = self._required_string(params, "exercise_id")
            submission = self.service.save_submission_draft(
                exercise_id=exercise_id,
                answer_text=params.get("answer_text", ""),
                submission_id=params.get("submission_id"),
                task_id=params.get("task_id"),
                expected_version=params.get("expected_version"),
                idempotency_key=params.get("idempotency_key"),
                source=str(params.get("source", "USER_WEB")),
            )
            return {"protocol_version": PROTOCOL_VERSION, **submission_summary(submission), "next_action": submission.next_action}
        if method == "submission.submit":
            submission = self.service.submit_submission(
                exercise_id=params.get("exercise_id"),
                answer_text=params.get("answer_text"),
                submission_id=params.get("submission_id"),
                task_id=params.get("task_id"),
                expected_version=params.get("expected_version"),
                idempotency_key=params.get("idempotency_key"),
                source=str(params.get("source", "USER_WEB")),
            )
            return {"protocol_version": PROTOCOL_VERSION, **submission_summary(submission), "next_action": submission.next_action}
        if method == "learning.progress.save":
            progress = self.service.save_learning_progress(
                course_id=self._required_string(params, "course_id"),
                lesson_id=self._required_string(params, "lesson_id"),
                progress_percent=params.get("progress_percent"),
                last_position=str(params.get("last_position", "")),
                source=str(params.get("source", "USER_WEB")),
            )
            return {"protocol_version": PROTOCOL_VERSION, "id": progress.id, "course_id": progress.course_id, "lesson_id": progress.lesson_id, "progress_percent": progress.progress_percent, "status": progress.status, "last_position": progress.last_position, "source": progress.source, "next_action": "继续阅读或开始对应练习；该字段仅表示阅读位置，不代表已掌握。"}
        if method == "course.import":
            path = self._resolve_path(params.get("path") or params.get("file"))
            return {"protocol_version": PROTOCOL_VERSION, **self.service.import_course_markdown(path)}
        if method == "review.write":
            feedback = self.service.write_review(
                self._required_string(params, "submission_id"),
                str(params.get("summary", "")),
                str(params.get("detail_markdown", "")),
                int(params.get("issue_count", 0)),
                bool(params.get("needs_revision", False)),
                params.get("idempotency_key"),
                source=str(params.get("source", "AGENT_CLI")),
                decision=params.get("decision"),
                next_action=str(params.get("next_action", "")),
            )
            return {"protocol_version": PROTOCOL_VERSION, "review_id": feedback.id, "submission_id": feedback.submission_id, "decision": feedback.decision, "next_action": feedback.next_action, "needs_revision": feedback.needs_revision}
        if method in {"submission.revise", "submission.retest"}:
            parent = self._required_string(params, "parent_submission_id")
            answer = params.get("answer_text", "")
            if not isinstance(answer, str):
                raise DomainError("INVALID_ARGUMENT", "answer_text 必须是文本。", "传入修正或复测答案文本。")
            kwargs = {"idempotency_key": params.get("idempotency_key"), "source": str(params.get("source", "USER_WEB"))}
            submission = self.service.revise_submission(parent, answer, **kwargs) if method.endswith("revise") else self.service.retest_submission(parent, answer, **kwargs)
            return {"protocol_version": PROTOCOL_VERSION, "submission_id": submission.id, "parent_submission_id": submission.parent_submission_id, "attempt_number": submission.attempt_number, "attempt_kind": submission.attempt_kind, "status": submission.status, "source": submission.source, "next_action": submission.next_action}
        if method == "snapshot.generate":
            target = date.fromisoformat(str(params["date"])) if params.get("date") else None
            snapshot = self.service.generate_snapshot(target_date=target, scope=str(params.get("scope", "today")))
            return {"protocol_version": PROTOCOL_VERSION, "snapshot_id": snapshot.id, "path": snapshot.relative_path}
        raise DomainError("METHOD_NOT_FOUND", f"未知 Engine 方法：{method}", "先读取 system.capabilities。")

    def _resolve_path(self, raw_path: Any) -> Path:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("course.import 需要 path。")
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = self.settings.workspace_root / candidate
        resolved = candidate.resolve()
        root = self.settings.workspace_root.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("文件路径必须位于 StudyFlow 工作区内。")
        if not resolved.is_file():
            raise FileNotFoundError(f"找不到课程文件：{raw_path}")
        return resolved

    def _doctor(self) -> dict[str, Any]:
        from sqlalchemy import text
        with self.service.session() as session:
            session.execute(text("SELECT 1"))
        return {"protocol_version": PROTOCOL_VERSION, "healthy": True, "workspace": {"root": str(self.settings.workspace_root), "exists": self.settings.workspace_root.is_dir(), "writable": self.settings.workspace_root.is_dir()}, "database": {"driver": self.settings.database_url.split(":", 1)[0], "status": "ready", "managed_by_app": self.settings.database_url.startswith("sqlite"), "reachable": True}, "capabilities": [item["name"] for item in CAPABILITIES], "next_action": "调用 study.today 查看当前学习状态。"}

    def _today(self, params: dict[str, Any]) -> dict[str, Any]:
        target = date.fromisoformat(str(params["date"])) if params.get("date") else date.today()
        data = self.service.dashboard(target, plan_line_id=params.get("plan_line_id"), task_kind=params.get("task_kind"))
        return {"protocol_version": PROTOCOL_VERSION, "date": target, "primary_task": data["primary_task"].title if data["primary_task"] else None, "current_course": course_summary(data["current_course"]) if data["current_course"] else None, "courses": [course_summary(course) for course in data["courses"]], "tasks": [{"id": task.id, "title": task.title, "status": task.status, "kind": task.task_kind} for task in data["tasks"]], "queue_counts": data["queue_counts"], "next_action": "优先打开 current_course，或处理 assignment.queue。"}

    @staticmethod
    def _required_string(params: dict[str, Any], name: str) -> str:
        value = params.get(name)
        if not isinstance(value, str) or not value.strip():
            raise DomainError("INVALID_ARGUMENT", f"缺少必填参数 {name}。", f"传入非空字符串 {name}。")
        return value.strip()

    @staticmethod
    def _plan(row: Any) -> dict[str, Any]:
        return {"id": row.id, "name": row.name, "priority": row.priority, "status": row.status}

    @staticmethod
    def _course(row: Any) -> dict[str, Any]:
        return {"id": row.id, "title": row.title, "summary": row.summary, "subject": row.subject, "content_type": row.content_type, "difficulty": row.difficulty, "source_type": row.source_type, "plan_line": row.plan_line.name if row.plan_line else None}

    @staticmethod
    def _course_progress(course: Any, data: dict[str, Any]) -> dict[str, Any]:
        return {"id": course.id, "title": course.title, "sequence": course.plan_sequence, "total": course.plan_total, "knowledge_total": course.knowledge_total, "knowledge_completed": course.knowledge_completed, "exercise_total": course.exercise_total, "exercise_completed": course.exercise_completed, "progress_percent": course.progress_percent}


def run_stdio(engine: StudyFlowEngine, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = engine.handle(request)
        except Exception as exc:
            response = make_response(None, error=error_payload(exc))
        stdout.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
        stdout.flush()


def main() -> None:
    # The desktop bridge always sends UTF-8 bytes, regardless of Windows locale.
    sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    engine = StudyFlowEngine()
    try:
        run_stdio(engine)
    finally:
        engine.close()


if __name__ == "__main__":
    main()
