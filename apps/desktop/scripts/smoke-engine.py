"""Run a frozen Engine over raw UTF-8 pipes, never against the learner's workspace."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--engine", type=Path, required=True)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[3]
temp_root = root / "apps" / "desktop" / "test-results" / "workspaces"
temp_root.mkdir(parents=True, exist_ok=True)
workspace = Path(tempfile.mkdtemp(prefix="studyflow-packed-utf8-", dir=temp_root))
env = {key: value for key, value in os.environ.items() if not key.startswith("STUDYFLOW_DATABASE")}
env["STUDYFLOW_WORKSPACE"] = str(workspace)
# Keep all extraction artifacts in the explicitly isolated test boundary.
temp_runtime = workspace / ".test-temp"; temp_runtime.mkdir()
env["TEMP"] = env["TMP"] = str(temp_runtime)
# Deliberately adversarial locale: the protocol must not inherit this encoding.
env["PYTHONIOENCODING"] = "gbk:surrogateescape"
subprocess.run([sys.executable, "-X", "utf8", "-m", "studyflow", "plan", "create", "--name", "冻结包回归", "--format", "json"],
               cwd=root / "packages" / "core", env=env, check=True, capture_output=True)
content = workspace / "content"; content.mkdir(exist_ok=True)
for index in (1, 2, 3):
    (content / f"知识点{index}.md").write_text(f"---\ncourse: 冻结包回归课\nlesson: 知识点{index}\nplan_line: 冻结包回归\nexercises:\n- title: 第{index}题\n  prompt: 说明中文与状态\n---\n\n# 知识点{index}\n\nUTF-8、中文和 emoji ✅ 必须原样保存。", encoding="utf-8")
proc = subprocess.Popen([str(args.engine.resolve())], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
checks = []

def call(method, params, expected_error=None):
    request = {"id": len(checks) + 1, "method": method, "params": params}
    proc.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")); proc.stdin.flush()
    line = proc.stdout.readline()
    assert line, "Engine unexpectedly exited"
    result = json.loads(line.decode("utf-8"))
    if expected_error:
        assert not result["ok"] and result["error"]["code"] == expected_error, result
    else:
        assert result["ok"], result
    checks.append({"method": method, "ok": result["ok"], "expected_error": expected_error})
    return result.get("data", result.get("error"))

try:
    call("system.doctor", {})
    for index in (1, 2, 3):
        imported = call("course.import", {"path": f"content/知识点{index}.md"})
    course_id = imported["course_id"]
    document = call("document.read", {"path": "content/知识点1.md"})
    assert "中文和 emoji ✅" in document["markdown"]
    detail = call("course.detail", {"course_id": course_id})
    ids = [lesson["exercises"][0]["id"] for lesson in detail["lessons"]]
    study = call("course.study.open", {"course_id": course_id, "idempotency_key": "packed-study-open"})
    study_id = study["study"]["id"]
    methods = {item["method"] for item in call("system.capabilities", {})["capabilities"]}
    assert {"course.notes.get", "course.notes.save"}.issubset(methods)
    assert not call("course.notes.get", {"study_session_id": study_id})["notes"]
    note_params = {"study_session_id": study_id, "lesson_id": study["lessons"][0]["id"],
        "text": "个人推导草稿 ✅，不是答案", "expected_version": 0, "idempotency_key": "packed-note-1"}
    note = call("course.notes.save", note_params)
    assert call("course.notes.save", note_params) == note
    note_params = {**note_params, "text": "第二次更新个人草稿 ✅", "expected_version": 1, "idempotency_key": "packed-note-2"}
    note = call("course.notes.save", note_params)
    assert note["note"]["version"] == 2
    call("course.notes.save", {**note_params, "text": "旧版本不能覆盖", "idempotency_key": "packed-note-stale"}, "VERSION_CONFLICT")
    assert call("course.notes.get", {"study_session_id": study_id})["notes"][0]["text"] == note_params["text"]
    assert not call("assignment.queue", {})["items"]
    assert {"plan.notebook.get", "plan.notebook.save"}.issubset(methods)
    plan_id=study["course"]["plan_line_id"]
    assert call("plan.notebook.get", {"plan_line_id":plan_id})["version"] == 0
    notebook_params={"plan_line_id":plan_id,"blocks":[{"id":"packed-continuous","text":"全计划连续理解 ✅"},
        {"id":"packed-quote","text":"带来源的理解","quote":"UTF-8、中文和 emoji ✅ 必须原样保存。","course_id":course_id,
         "lesson_id":study["lessons"][0]["id"],"source_study_id":study_id}],"expected_version":0,"idempotency_key":"packed-notebook"}
    notebook=call("plan.notebook.save",notebook_params)
    assert call("plan.notebook.save",notebook_params)==notebook
    assert notebook["blocks"][1]["content_hash"]==study["study"]["content_hash"]
    call("plan.notebook.save",{**notebook_params,"idempotency_key":"packed-notebook-stale"},"VERSION_CONFLICT")
    readback=call("plan.notebook.get",{"plan_line_id":plan_id})
    assert readback["blocks"][0]["text"]=="全计划连续理解 ✅" and readback["legacy_notes"][0]["text"]==note_params["text"]
    assert not call("assignment.queue",{})["items"]
    assert study["course"]["study_status"] == "IN_PROGRESS"
    progress = call("course.study.progress.save", {"study_session_id": study_id,
        "lesson_id": study["lessons"][0]["id"], "progress_percent": 100, "last_position": "{}", "expected_version": 1})
    assert progress["version"] == 2
    assert call("course.study.get", {"study_session_id": study_id})["lessons"][0]["progress"]["status"] == "COMPLETED"
    source = content / "知识点1.md"
    source.write_text(source.read_text(encoding="utf-8") + "\n\n新版材料，不能改变已开始的学习。", encoding="utf-8")
    resumed = call("course.study.open", {"course_id": course_id, "idempotency_key": "packed-resume"})
    assert resumed["study"]["id"] == study_id and resumed["study"]["source_changed"]
    assert "新版材料" not in resumed["lessons"][0]["rendered_html"]
    answer = "70度正常，71度告警。\n中文原样往返 ✅"
    single = call("submission.draft.save", {"exercise_id": ids[0], "answer_text": answer, "idempotency_key": "unicode-single-save"})
    assert call("submission.get", {"submission_id": single["id"]})["answer_text"] == answer
    formal = call("submission.submit", {"exercise_id": ids[0], "submission_id": single["id"], "expected_version": single["version"], "answer_text": answer, "idempotency_key": "unicode-single-submit"})
    call("review.write", {"submission_id": formal["id"], "summary": "请修正边界", "detail_markdown": "**原答案**保留，补充理由。", "decision": "REVISION_REQUIRED", "idempotency_key": "unicode-review"})
    payload = [{"exercise_id": identifier, "answer_text": answer + f" 第{i + 1}题"} for i, identifier in enumerate(ids)]
    payload[0]["parent_submission_id"] = formal["id"]
    blank = [dict(item) for item in payload]; blank[1]["answer_text"] = ""
    call("course.answers.submit", {"course_id": course_id, "answers": blank, "idempotency_key": "batch-blank"}, "INCOMPLETE_COURSE_ANSWERS")
    untouched = call("course.answers.get", {"course_id": course_id})
    assert all(item["draft"] is None for item in untouched["answers"])
    params = {"course_id": course_id, "answers": payload, "idempotency_key": "batch-save"}
    saved = call("course.answers.draft.save", params)
    assert call("course.answers.draft.save", params) == saved
    for iteration in (2, 3):
        repeated = [{**entry, "submission_id": row["id"], "expected_version": row["version"]}
                    for entry, row in zip(payload, saved["submissions"])]
        previous_versions = [row["version"] for row in saved["submissions"]]
        saved = call("course.answers.draft.save", {"course_id": course_id,
            "answers": repeated, "idempotency_key": f"batch-repeat-{iteration}"})
        assert [row["version"] for row in saved["submissions"]] == [version + 1 for version in previous_versions]
    submit_payload = [{**item, "submission_id": row["id"], "expected_version": row["version"]} for item, row in zip(payload, saved["submissions"])]
    stale = [dict(item) for item in submit_payload]; stale[1]["expected_version"] += 1
    call("course.answers.submit", {"course_id": course_id, "answers": stale, "idempotency_key": "stale-batch"}, "VERSION_CONFLICT")
    after_stale = call("course.answers.get", {"course_id": course_id})
    expected_versions = {entry["exercise_id"]: row["version"] for entry, row in zip(payload, saved["submissions"])}
    assert all(item["draft"]["version"] == expected_versions[item["exercise_id"]] for item in after_stale["answers"])
    params = {"course_id": course_id, "answers": submit_payload, "idempotency_key": "batch-submit"}
    result = call("course.answers.submit", params)
    frozen = call("submission.get", {"submission_id": result["submissions"][1]["id"]})
    assert frozen["study_context"]["study_session_id"] == study_id
    assert "新版材料" not in frozen["study_context"]["markdown"]
    assert frozen["batch_id"] == result["batch_id"]
    assert call("course.answers.submit", params) == result
    queue = call("assignment.queue", {})
    assert len(queue["waiting_review"]) == 3
    assert call("submission.get", {"submission_id": formal["id"]})["answer_text"] == answer
    for i, row in enumerate(result["submissions"]):
        call("review.write", {"submission_id": row["id"], "summary": "需要复测" if i == 0 else "通过", "decision": "RETEST_REQUIRED" if i == 0 else "PASSED", "idempotency_key": f"batch-review-{i}"})
    task = call("review.retest.publish", {"parent_submission_id": result["submissions"][0]["id"], "title": "独立复测题", "prompt": "说明新的温度边界条件及原因。", "objective": "验证边界条件迁移", "idempotency_key": "batch-retest-task"})
    retest = call("course.answers.submit", {"course_id": course_id, "answers": [{"exercise_id": ids[0], "answer_text": "新的复测答案 ✅", "parent_submission_id": result["submissions"][0]["id"], "retest_task_id": task["id"]}], "idempotency_key": "batch-retest"})
    assert retest["submissions"][0]["attempt_kind"] == "RETEST"
    call("review.write", {"submission_id": retest["submissions"][0]["id"], "summary": "通过", "decision": "PASSED", "idempotency_key": "retest-pass"})
    final = call("assignment.queue", {})
    assert not final["items"]
    log = workspace / ".studyflow/logs/engine-errors.jsonl"
    assert not log.exists(), log.read_text(encoding="utf-8") if log.exists() else ""
finally:
    proc.stdin.close()
    try: proc.wait(timeout=15)
    except subprocess.TimeoutExpired: proc.kill(); proc.wait(); raise
    assert proc.returncode == 0, proc.stderr.read().decode("utf-8", errors="replace")
report = {"success": True, "workspace": str(workspace), "checks": checks, "check_count": len(checks), "raw_utf8_roundtrip": True, "atomic_rollback": True, "business_acceptance": "not_evaluated"}
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
