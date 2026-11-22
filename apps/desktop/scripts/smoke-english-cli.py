"""Run the public Agent-neutral CLI against one isolated synthetic workspace."""
import argparse
import json
from pathlib import Path

from rust_smoke_support import NativeCli

ROOT = Path(__file__).resolve().parents[3]


def main(desktop, workspace, evidence):
    cli = NativeCli(desktop, workspace, evidence, record_receipts=True)
    call = cli.command
    method = cli.call
    RESULTS = evidence
    call("version")
    capabilities = call("capabilities")
    assert "studyflow.course-package/2" in capabilities["content"]["course_package_schemas"]
    assert any(c["method"] == "course.english.retest-save" for c in capabilities["engine_capabilities"])
    doctor = call("doctor")
    assert doctor["healthy"] and doctor["workspace"]["writable"]
    method("system.schema", {"method": "course.english.save"})
    plan = call("plan", "create", "--name", "Synthetic English")
    for sample in ["english-course-package-v6.json", "course-package.json", "english-course-package.json"]:
        source = ROOT / "skills/studyflow-agent/examples" / sample
        validated = call("course", "validate-package", "--file", str(source))
        assert validated["valid"]
        if sample=="english-course-package.json":
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
    (RESULTS / "result.json").write_text(json.dumps({"checks": len(cli.receipts), "receipts": cli.receipts, "business_acceptance": "not_evaluated"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "checks": len(cli.receipts), "workspace": str(workspace)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.workspace.mkdir(parents=True, exist_ok=False)
    args.evidence.mkdir(parents=True, exist_ok=True)
    main(args.desktop.resolve(strict=True), args.workspace.resolve(), args.evidence.resolve())
