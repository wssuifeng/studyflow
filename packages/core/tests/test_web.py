from fastapi.testclient import TestClient

from studyflow.web import create_app


def test_today_and_course_pages_render(app_service):
    seeded = app_service.seed_demo()
    client = TestClient(create_app(service=app_service))
    today = client.get("/today")
    assert today.status_code == 200
    assert "TODAY LEARNING" in today.text
    assert "今日学习" in today.text
    assert "当前推进点" not in today.text
    assert "3 个知识点" in today.text
    assert client.get("/console").status_code == 200
    course = client.get(f"/course/{seeded['course_id']}")
    assert course.status_code == 200
    assert "保存并提交" in course.text


def test_submit_form_redirects_to_submission(app_service):
    seeded = app_service.seed_demo()
    client = TestClient(create_app(service=app_service))
    response = client.post(f"/exercises/{seeded['exercise_id']}/submit", data={"answer_text": "我的答案", "task_id": seeded["task_id"]}, follow_redirects=False)
    assert response.status_code == 303
    assert "/submission/" in response.headers["location"]
    detail = client.get(response.headers["location"])
    assert "等待外部 Agent 批改" in detail.text


def test_today_filter_and_generic_course_metadata(app_service, tmp_path):
    from datetime import date

    plan = app_service.create_plan_line("English CET-4")
    app_service.create_task("Read a short passage", date.today(), "READING", plan_line_id=plan.id)
    client = TestClient(create_app(service=app_service))
    response = client.get(f"/today?plan_line_id={plan.id}")
    assert response.status_code == 200
    assert "English CET-4" in response.text
    assert "Read a short passage" in response.text
    assert "Java就业主线" not in response.text



def test_plan_pages_and_multi_knowledge_course(app_service):
    seeded = app_service.seed_demo()
    client = TestClient(create_app(service=app_service))
    plans = client.get("/plans")
    assert plans.status_code == 200
    assert "我的计划" in plans.text
    detail = client.get(f"/plans/{seeded['plan_line_id']}")
    assert detail.status_code == 200
    assert "课程顺序" in detail.text
    course = client.get(f"/course/{seeded['course_id']}")
    assert course.text.count("KNOWLEDGE POINT") == 3


def test_passed_submission_page_offers_both_followups(app_service):
    seeded = app_service.seed_demo()
    submission = app_service.submit_answer(seeded["exercise_id"], "答案")
    app_service.write_review(submission.id, "已掌握", decision="PASSED")
    client = TestClient(create_app(service=app_service))
    page = client.get(f"/submission/{submission.id}")
    assert page.status_code == 200
    assert page.text.count("提交修正版") == 1
    assert page.text.count("提交复测版") == 1


def test_browser_engine_bridge_uses_shared_service_and_rejects_non_local_callers(app_service):
    from studyflow.web import create_app
    seeded = app_service.seed_demo()
    client = TestClient(create_app(service=app_service, enable_browser_bridge=True))
    headers = {"origin": "http://127.0.0.1:1420", "host": "127.0.0.1:8787", "content-type": "application/json", "x-studyflow-client": "studyflow-ui"}
    response = client.post("/api/engine", json={"id": 1, "method": "course.detail", "params": {"course_id": seeded["course_id"]}}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["course"]["id"] == seeded["course_id"]
    rejected = client.post("/api/engine", json={"id": 2, "method": "system.doctor", "params": {}}, headers={**headers, "origin": "https://evil.example"})
    assert rejected.status_code == 403
