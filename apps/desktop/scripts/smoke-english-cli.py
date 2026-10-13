"""Run the public Agent-neutral CLI against one isolated synthetic workspace."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "apps/desktop/test-results/english-cli"
RESULTS.mkdir(parents=True, exist_ok=True)
workspace = Path(tempfile.mkdtemp(prefix="synthetic-", dir=RESULTS)).resolve()
env = {**os.environ, "STUDYFLOW_WORKSPACE": str(workspace), "STUDYFLOW_DATABASE_URL": "sqlite:///"+(workspace/"cli.db").as_posix()}
receipts = []


def call(*args):
    result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "studyflow", *args, "--format", "json"],
                            env=env, cwd=workspace, capture_output=True, text=True, encoding="utf-8", timeout=30)
    parsed = json.loads(result.stdout)
    assert result.returncode == 0 and parsed.get("ok") is True, (args, result.returncode, parsed)
    receipts.append({"args": args, "exit_code": result.returncode, "response": parsed})
    return parsed


def method(name, params=None):
    path = workspace / "request.json"
    path.write_text(json.dumps(params or {}, ensure_ascii=False), encoding="utf-8")
    return call("call", "--method", name, "--file", str(path))


call("version")
capabilities = call("capabilities")
assert "studyflow.course-package/2" in capabilities["content"]["course_package_schemas"]
assert any(c["method"] == "course.english.retest-save" for c in capabilities["engine_capabilities"])
doctor = call("doctor")
assert doctor["healthy"] and doctor["workspace"]["writable"]
method("system.schema", {"method": "course.english.save"})
plan = call("plan", "create", "--name", "Synthetic English")
for sample in ["course-package.json", "english-course-package.json"]:
    source = ROOT / "skills/studyflow-agent/examples" / sample
    validated = call("course", "validate-package", "--file", str(source))
    assert validated["valid"]
    if sample.startswith("english"):
        course = call("course", "import-package", "--file", str(source))
        detail = call("course", "detail", "--id", course["course_id"])
        assert detail["course"]["learning_mode"] == "english"
        assert len(detail["lessons"][0]["exercises"]) == 2
call("plan", "detail", "--id", plan["id"])
method("mistakes.summary", {"plan_line_id": plan["id"], "domain": "english"})
# This is an explicitly synthetic engineering test, never a real learner round.
opened = method("course.study.open", {"course_id": course["course_id"], "plan_line_id": plan["id"], "idempotency_key": "synthetic-cli-open"})
view = method("course.english.get", {"study_session_id": opened["study"]["id"]})
assert len(view["items"]) == 2 and "target" not in view["items"][0]
(RESULTS / "result.json").write_text(json.dumps({"checks": len(receipts), "receipts": receipts, "business_acceptance": "not_evaluated"}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"ok": True, "checks": len(receipts), "workspace": str(workspace)}, ensure_ascii=False))
