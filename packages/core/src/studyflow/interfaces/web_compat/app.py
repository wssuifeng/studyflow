from __future__ import annotations

from datetime import date
import os
from urllib.parse import urlparse

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from studyflow.config import Settings
from studyflow.infrastructure.resources import resource_root
from studyflow.db import build_engine, build_session_factory, init_db
from studyflow.domain import DomainError
from studyflow.engine import StudyFlowEngine
from studyflow.seed import seed
from studyflow.services import AppService


def create_app(settings: Settings | None = None, service: AppService | None = None, *, enable_browser_bridge: bool | None = None) -> FastAPI:
    settings = settings or (service.settings if service else Settings.from_env())
    service_settings = service.settings if service else settings
    settings.ensure_layout()
    if service is None:
        engine = build_engine(settings)
        init_db(engine)
        service = AppService(settings, build_session_factory(engine))
    app = FastAPI(title="StudyFlow", version="1.1.0")
    app.state.settings = settings
    app.state.service = service
    assets = resource_root()
    static_root = settings.static_root if (settings.static_root / "app.css").is_file() else assets / "static"
    app.mount("/static", StaticFiles(directory=static_root), name="static")
    templates = Jinja2Templates(directory=[str(settings.templates_root), str(assets / "templates")])
    browser_bridge = enable_browser_bridge if enable_browser_bridge is not None else os.getenv("STUDYFLOW_ENABLE_BROWSER_BRIDGE") == "1"
    dispatcher = StudyFlowEngine(service_settings, service=service)

    @app.post("/api/engine")
    async def browser_engine(request: Request) -> JSONResponse:
        if not browser_bridge:
            return JSONResponse({"error": "Browser bridge is disabled."}, status_code=404)
        origins = {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in (1420, service_settings.port)}
        host = urlparse("http://" + request.headers.get("host", "")).hostname
        if (request.headers.get("origin") not in origins or host not in {"localhost", "127.0.0.1"}
                or request.headers.get("x-studyflow-client") != "studyflow-ui"
                or request.headers.get("content-type", "").split(";", 1)[0] != "application/json"):
            return JSONResponse({"error": "Only the local StudyFlow interface may call this bridge."}, status_code=403)
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        from fastapi.encoders import jsonable_encoder
        return JSONResponse(jsonable_encoder(dispatcher.handle(payload)))


    @app.get("/", response_class=HTMLResponse)
    def root() -> RedirectResponse:
        return RedirectResponse("/today", status_code=303)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": "studyflow"}

    @app.get("/today", response_class=HTMLResponse)
    def today(request: Request, date_value: str | None = None, plan_line_id: str | None = None, task_kind: str | None = None, message: str | None = None) -> HTMLResponse:
        target = date.fromisoformat(date_value) if date_value else date.today()
        data = service.dashboard(target, plan_line_id=plan_line_id, task_kind=task_kind)
        return templates.TemplateResponse(request=request, name="today.html", context={"request": request, "data": data, "message": message})

    @app.get("/console", response_class=HTMLResponse)
    def console(request: Request, date_value: str | None = None, message: str | None = None) -> HTMLResponse:
        target = date.fromisoformat(date_value) if date_value else date.today()
        data = service.dashboard(target)
        return templates.TemplateResponse(request=request, name="today.html", context={"request": request, "data": data, "message": message, "console": True})

    @app.get("/plans", response_class=HTMLResponse)
    def plans(request: Request, message: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="plans.html", context={"request": request, "plans": service.plan_overviews(), "message": message})

    @app.get("/plans/{plan_line_id}", response_class=HTMLResponse)
    def plan_detail(request: Request, plan_line_id: str, message: str | None = None) -> HTMLResponse:
        plan = service.get_plan_detail(plan_line_id)
        if not plan:
            return templates.TemplateResponse(request=request, name="error.html", context={"request": request, "message": "计划不存在"}, status_code=404)
        return templates.TemplateResponse(request=request, name="plan_detail.html", context={"request": request, "plan": plan, "message": message})

    @app.post("/tasks/{task_id}/status")
    def task_status(task_id: str, status: str = Form(...), reason: str = Form(""), next_action: str = Form("")) -> RedirectResponse:
        try:
            service.update_task_status(task_id, status, reason, next_action)
            return RedirectResponse("/today?message=任务状态已更新", status_code=303)
        except DomainError as exc:
            return RedirectResponse(f"/today?message={exc.message}", status_code=303)

    @app.get("/course/{course_id}", response_class=HTMLResponse)
    def course(request: Request, course_id: str) -> HTMLResponse:
        item = service.get_course(course_id)
        if not item:
            return templates.TemplateResponse(request=request, name="error.html", context={"request": request, "message": "课程不存在"}, status_code=404)
        return templates.TemplateResponse(request=request, name="course.html", context={"request": request, "course": item})

    @app.post("/exercises/{exercise_id}/submit")
    async def submit(request: Request, exercise_id: str, answer_text: str = Form(...), task_id: str | None = Form(None)) -> RedirectResponse:
        try:
            submission = service.submit_answer(exercise_id, answer_text, task_id, source="USER_WEB")
            return RedirectResponse(f"/submission/{submission.id}?message=作答已提交，等待 Agent 批改", status_code=303)
        except DomainError as exc:
            return RedirectResponse(f"/today?message={exc.message}", status_code=303)

    @app.post("/submissions/{submission_id}/revise")
    def revise_submission(submission_id: str, answer_text: str = Form(...)) -> RedirectResponse:
        try:
            submission = service.revise_submission(submission_id, answer_text)
            return RedirectResponse(f"/submission/{submission.id}?message=修正版已提交，等待 Agent 批改", status_code=303)
        except DomainError as exc:
            return RedirectResponse(f"/submission/{submission_id}?message={exc.message}", status_code=303)

    @app.post("/submissions/{submission_id}/retest")
    def retest_submission(submission_id: str, answer_text: str = Form(...)) -> RedirectResponse:
        try:
            submission = service.retest_submission(submission_id, answer_text)
            return RedirectResponse(f"/submission/{submission.id}?message=复测版已提交，等待 Agent 批改", status_code=303)
        except DomainError as exc:
            return RedirectResponse(f"/submission/{submission_id}?message={exc.message}", status_code=303)

    @app.get("/submission/{submission_id}", response_class=HTMLResponse)
    def submission(request: Request, submission_id: str, message: str | None = None) -> HTMLResponse:
        item = service.get_submission(submission_id)
        if not item:
            return templates.TemplateResponse(request=request, name="error.html", context={"request": request, "message": "作答记录不存在"}, status_code=404)
        return templates.TemplateResponse(request=request, name="submission.html", context={"request": request, "submission": item, "message": message})

    @app.get("/documents", response_class=HTMLResponse)
    def documents(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="documents.html", context={"request": request, "documents": service.list_documents()})

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    from studyflow.config import Settings
    from studyflow.seed import seed

    settings = Settings.from_env()
    seed(settings)
    uvicorn.run(app, host=settings.host, port=settings.port)
