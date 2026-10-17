"""W1 design §3/§8: the CLI ``course quality-check`` wraps the Core module read-only.

The CLI contract under test (design ``docs/30_系统设计/W1生成侧质量工具与接口详细设计-v1.md`` §3):

- ``--file`` reads raw bytes, hashes them as ``package_sha256`` and parses JSON
  as UTF-8(-BOM); unreadable files fail with ``DOCUMENT_UNREADABLE``, illegal
  JSON or an illegal ``--long-section-chars`` threshold fails with
  ``INVALID_ARGUMENT`` (§3 error-code table).
- ``--blueprint``/``--sources``/``--related``(repeatable)/``--validation-receipt``/
  ``--rendering-receipt`` are forwarded to
  ``studyflow.modules.courses.authoring_quality.analyze``.
- Output is ``{"ok": true, ...report}``; errors follow the ``validate-package``
  ``fail(exc, read_only=True)`` shape and never initialize a workspace or DB.
- Acceptance §8.1 (violation fixtures hit rules/classification, deterministic
  errors block), §8.2 (legal synthetic sample gains no new advisory) and §8.4
  (one byte changed inside the package flips receipt slots to
  ``unbound_receipt``).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from studyflow.cli import app

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PACKAGE = REPO_ROOT / "skills" / "studyflow-agent" / "examples" / "course-package.json"

RULE_VERSION = "authoring-quality/4"
REPORT_SCHEMA = "studyflow.authoring-quality/2"
NEW_RULES = {
    "MISSING_MAIN_SECTION",
    "ENGLISH_PROMPT_LANGUAGE_REVIEW",
    "VARIANT_STRUCTURE_CANDIDATE",
    "NEAR_TEMPLATE_CANDIDATE",
    "UNMAPPED_EXERCISE",
}
DETERMINISTIC_RULES = {"DUPLICATE_VARIANT", "BLUEPRINT_REFERENCE_MISSING"}


def write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def legal_course(package_id: str = "quality-cli-legal") -> dict:
    """A clean general-course synthetic package: no advisory at default thresholds."""
    return {
        "schema": "studyflow.course-package/1",
        "package_id": package_id,
        "plan_line": "合成计划",
        "course": {"title": "质量检查合法夹具"},
        "lessons": [
            {
                "id": "l1",
                "title": "合法知识点",
                "blocks": [
                    {
                        "id": "b1",
                        "type": "concept",
                        "title": "概念",
                        "sections": [{"id": "s1", "title": "主干", "role": "main", "body": "短主干正文。"}],
                    }
                ],
                "exercises": [
                    {
                        "id": "q1",
                        "title": "练习",
                        "prompt": "说明存储元件的作用",
                        "review_reference": {"answer": "存储元件负责保持数据。", "criteria": ["正确"]},
                    }
                ],
            }
        ],
    }


def english_course(prompt: str = "说明这句英语的意思", english: dict | None = None) -> dict:
    """A clean english synthetic package; ``english`` patches the english spec."""
    spec = {
        "target": "I do not read.",
        "accepted_answers": [],
        "sentence_parts": [],
        "phonetic": "/aɪ du nɒt riːd/",
    }
    if english:
        spec.update(english)
    return {
        "schema": "studyflow.course-package/6",
        "package_id": "quality-cli-english",
        "plan_line": "合成英语计划",
        "course": {"title": "英语质量夹具", "learning_mode": "english"},
        "lessons": [
            {
                "id": "l1",
                "title": "英语知识点",
                "blocks": [
                    {
                        "id": "b1",
                        "type": "concept",
                        "title": "概念",
                        "sections": [{"id": "s1", "title": "主干", "role": "main", "body": "短正文。"}],
                    }
                ],
                "exercises": [
                    {
                        "id": "q1",
                        "title": "英语练习",
                        "prompt": prompt,
                        "review_reference": {"answer": "我不阅读。", "criteria": ["正确"]},
                        "english": spec,
                    }
                ],
            }
        ],
    }


def invoke_quality(file_path: Path, *extra: str):
    return CliRunner().invoke(
        app, ["course", "quality-check", "--file", str(file_path), "--format", "json", *extra]
    )


def payload_of(result) -> dict:
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    return payload


def error_payload_of(result) -> dict:
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout or result.stderr)
    assert payload["ok"] is False
    return payload


def rules_of(payload: dict) -> list[str]:
    return [advisory["rule"] for advisory in payload["advisories"]]


def advisory_of(payload: dict, rule: str) -> dict:
    matches = [advisory for advisory in payload["advisories"] if advisory["rule"] == rule]
    assert matches, f"rule {rule} not hit; advisories were {rules_of(payload)}"
    return matches[0]


# ---- CLI contract: report shape, byte binding, forwarding (§3/§5) ----


def test_quality_check_reports_v2_schema_bound_to_file_bytes(tmp_path):
    path = write_json(tmp_path / "course.json", legal_course())
    payload = payload_of(invoke_quality(path))
    assert payload["report_schema"] == REPORT_SCHEMA
    assert payload["rule_version"] == RULE_VERSION
    assert payload["package_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert payload["advisories"] == [] and payload["blocked"] is False
    assert payload["source_verification"] == "not_provided"
    assert payload["protocol_validation"] == "not_provided"
    assert payload["blueprint_provided"] is False
    assert payload["capability_config"] == {"rule_version": RULE_VERSION, "options": {"long_section_chars": 400}}
    assert payload["semantic_ids"] == {
        "package_id": "quality-cli-legal",
        "lesson_ids": ["l1"],
        "exercise_ids": ["q1"],
    }
    gate = payload["publication_gate"]
    assert set(gate) == {"protocol", "content", "rendering", "writeback"}
    assert gate["protocol"] == "not_provided"
    assert gate["rendering"] == "not_provided"
    assert gate["writeback"] == "not_provided"
    assert gate["content"]["status"] == "self_reference" and gate["content"]["report_sha256"]
    assert payload["teaching_chain_list"] == [
        {"lesson_id": "l1", "chains": [], "english_exercises_without_chain": []}
    ]
    assert set(payload["conclusion_summary"]) == {
        "deterministic_error", "content_defect", "review_required", "presentation_defect", "advisory",
    }


def test_quality_check_reads_utf8_bom_and_hashes_raw_bytes(tmp_path):
    path = tmp_path / "bom.json"
    path.write_text(json.dumps(legal_course(), ensure_ascii=False), encoding="utf-8-sig")
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    payload = payload_of(invoke_quality(path))
    assert payload["package_sha256"] == hashlib.sha256(raw).hexdigest()
    assert payload["advisories"] == []


def test_declared_sources_are_recorded_not_verified(tmp_path):
    path = write_json(tmp_path / "course.json", legal_course())
    sources = write_json(
        tmp_path / "sources.json", [{"title": "作者声明来源", "url": "https://example.invalid"}]
    )
    assert payload_of(invoke_quality(path))["source_verification"] == "not_provided"
    payload = payload_of(invoke_quality(path, "--sources", str(sources)))
    assert payload["source_verification"] == "declared_not_verified"


def test_long_section_chars_threshold_is_applied_and_reported(tmp_path):
    data = legal_course()
    data["lessons"][0]["blocks"][0]["sections"][0]["body"] = "字" * 250
    path = write_json(tmp_path / "course.json", data)
    payload = payload_of(invoke_quality(path, "--long-section-chars", "200"))
    assert payload["capability_config"]["options"]["long_section_chars"] == 200
    assert advisory_of(payload, "LONG_SECTION_REVIEW")["evidence"]["threshold"] == 200
    default = payload_of(invoke_quality(path))
    assert "LONG_SECTION_REVIEW" not in rules_of(default)
    assert default["capability_config"]["options"]["long_section_chars"] == 400


def test_missing_file_flag_is_required(tmp_path):
    result = CliRunner().invoke(app, ["course", "quality-check", "--format", "json"])
    assert result.exit_code != 0


# ---- §8.1 violation fixtures: each rule hit with its classification ----


def test_violation_fixture_missing_reference_answer(tmp_path):
    data = legal_course()
    del data["lessons"][0]["exercises"][0]["review_reference"]
    payload = payload_of(invoke_quality(write_json(tmp_path / "course.json", data)))
    advisory = advisory_of(payload, "REFERENCE_MISSING")
    assert advisory["classification"] == "review_required"
    assert advisory["path"] == "/lessons/0/exercises/0/review_reference"
    assert payload["blocked"] is False


def test_violation_fixture_duplicate_variant_blocks(tmp_path):
    data = english_course(english={"accepted_answers": ["I do not read."]})
    payload = payload_of(invoke_quality(write_json(tmp_path / "course.json", data)))
    advisory = advisory_of(payload, "DUPLICATE_VARIANT")
    assert advisory["classification"] == "deterministic_error"
    assert advisory["path"] == "/lessons/0/exercises/0/english"
    assert advisory["evidence"]["variant_index"] == 1
    assert payload["blocked"] is True
    assert "DUPLICATE_VARIANT" in payload["conclusion_summary"]["deterministic_error"]["rules"]


def test_violation_fixture_blueprint_reference_missing_blocks(tmp_path):
    data = english_course()
    blueprint = write_json(
        tmp_path / "blueprint.json", {"objectives": [{"exercise_ids": ["ghost"], "teaching_ids": ["b1"]}], "frames": ["frame-a"]}
    )
    payload = payload_of(invoke_quality(write_json(tmp_path / "course.json", data), "--blueprint", str(blueprint)))
    advisory = advisory_of(payload, "BLUEPRINT_REFERENCE_MISSING")
    assert advisory["classification"] == "deterministic_error"
    assert advisory["path"] == "/blueprint/objectives/0"
    assert advisory["evidence"] == {"exercise_ids": ["ghost"], "teaching_ids": []}
    assert payload["blueprint_provided"] is True
    assert payload["metrics"]["declared_frames"] == ["frame-a"]
    assert payload["blocked"] is True


def test_violation_fixture_unmapped_exercise_is_review(tmp_path):
    data = english_course()
    data["lessons"][0]["exercises"].append(
        {"id": "q2", "title": "练习二", "prompt": "再读一遍", "review_reference": {"answer": "再读"}}
    )
    blueprint = write_json(
        tmp_path / "blueprint.json", {"objectives": [{"exercise_ids": ["q1"], "teaching_ids": ["b1"]}]}
    )
    payload = payload_of(invoke_quality(write_json(tmp_path / "course.json", data), "--blueprint", str(blueprint)))
    advisory = advisory_of(payload, "UNMAPPED_EXERCISE")
    assert advisory["classification"] == "review_required"
    assert advisory["path"] == "/lessons/0/exercises/1"
    assert advisory["evidence"]["exercise_id"] == "q2"
    assert payload["blocked"] is False
    unscoped = payload_of(invoke_quality(write_json(tmp_path / "plain.json", data)))
    assert "UNMAPPED_EXERCISE" not in rules_of(unscoped)


def test_violation_fixture_all_supplement_sections(tmp_path):
    data = legal_course()
    data["lessons"][0]["blocks"][0]["sections"] = [
        {"id": "s1", "title": "补充", "role": "supplement", "body": "短"},
        {"id": "s2", "title": "补充二", "role": "supplement", "body": "短"},
    ]
    payload = payload_of(invoke_quality(write_json(tmp_path / "course.json", data)))
    advisory = advisory_of(payload, "MISSING_MAIN_SECTION")
    assert advisory["classification"] == "review_required"
    assert advisory["path"] == "/lessons/0/blocks/0/sections"
    assert advisory["evidence"]["roles"] == ["supplement"]
    assert payload["blocked"] is False


@pytest.mark.parametrize("prompt,reason", [
    ("Translate the sentence.", "same_language_as_target"),
    ("  ", "empty_prompt"),
])
def test_violation_fixture_english_prompt_language(tmp_path, prompt, reason):
    data = english_course(prompt=prompt)
    payload = payload_of(invoke_quality(write_json(tmp_path / "course.json", data)))
    advisory = advisory_of(payload, "ENGLISH_PROMPT_LANGUAGE_REVIEW")
    assert advisory["classification"] == "review_required"
    assert advisory["path"] == "/lessons/0/exercises/0/prompt"
    assert advisory["evidence"]["reason"] == reason
    assert payload["blocked"] is False


def test_violation_fixture_near_template_reuse_with_related(tmp_path):
    data = english_course(
        english={"target": "I like tea.", "phonetic": "/aɪ/", "progression": {"chain_id": "c1", "stage": "vocabulary"}}
    )
    near = {
        "lessons": [
            {"id": "r1", "exercises": [
                {"id": "rq1", "english": {"target": "I like coffee.", "progression": {"chain_id": "c1", "stage": "vocabulary"}}}
            ]}
        ]
    }
    far = {
        "lessons": [
            {"id": "r2", "exercises": [
                {"id": "rq2", "english": {"target": "You drink milk now.", "progression": {"chain_id": "c1", "stage": "vocabulary"}}}
            ]}
        ]
    }
    path = write_json(tmp_path / "course.json", data)
    near_file = write_json(tmp_path / "near.json", near)
    far_file = write_json(tmp_path / "far.json", far)
    payload = payload_of(invoke_quality(path, "--related", str(near_file), "--related", str(far_file)))
    advisory = advisory_of(payload, "NEAR_TEMPLATE_CANDIDATE")
    assert advisory["classification"] == "review_required"
    assert advisory["evidence"]["related_target"] == "I like coffee."
    assert advisory["evidence"]["stage"] == "vocabulary"
    assert payload["blocked"] is False
    far_only = payload_of(invoke_quality(path, "--related", str(far_file)))
    assert "NEAR_TEMPLATE_CANDIDATE" not in rules_of(far_only)


def test_combined_violation_fixture_hits_each_rule_and_blocks(tmp_path):
    data = english_course(
        prompt="Translate the sentence.",
        english={
            "target": "I like tea.",
            "phonetic": "/aɪ/",
            "progression": {"chain_id": "c1", "stage": "vocabulary"},
            "accepted_answers": ["I like tea."],
        },
    )
    del data["lessons"][0]["exercises"][0]["review_reference"]
    data["lessons"][0]["blocks"][0]["sections"] = [{"id": "s1", "title": "补充", "role": "supplement", "body": "短"}]
    path = write_json(tmp_path / "course.json", data)
    blueprint = write_json(
        tmp_path / "blueprint.json", {"objectives": [{"exercise_ids": ["ghost"], "teaching_ids": ["b1"]}]}
    )
    near = {
        "lessons": [
            {"id": "r1", "exercises": [
                {"id": "rq1", "english": {"target": "I like coffee.", "progression": {"chain_id": "c1", "stage": "vocabulary"}}}
            ]}
        ]
    }
    near_file = write_json(tmp_path / "near.json", near)
    payload = payload_of(invoke_quality(path, "--blueprint", str(blueprint), "--related", str(near_file)))
    hit = set(rules_of(payload))
    assert {"REFERENCE_MISSING", "DUPLICATE_VARIANT", "BLUEPRINT_REFERENCE_MISSING",
            "MISSING_MAIN_SECTION", "ENGLISH_PROMPT_LANGUAGE_REVIEW", "NEAR_TEMPLATE_CANDIDATE"} <= hit
    assert payload["blocked"] is True
    summary = payload["conclusion_summary"]
    assert set(summary["deterministic_error"]["rules"]) == {"DUPLICATE_VARIANT", "BLUEPRINT_REFERENCE_MISSING"}
    assert "REFERENCE_MISSING" in summary["review_required"]["rules"]
    assert "MISSING_MAIN_SECTION" in summary["review_required"]["rules"]
    assert payload["manual_review_required"]


# ---- §8.2 legal synthetic sample gains no new advisory ----


def test_legal_example_package_has_no_new_rule_false_positive():
    assert EXAMPLE_PACKAGE.is_file(), f"missing synthetic sample: {EXAMPLE_PACKAGE}"
    payload = payload_of(invoke_quality(EXAMPLE_PACKAGE))
    assert payload["metrics"]["exercises"] == 1
    assert payload["blocked"] is False
    hit = set(rules_of(payload))
    assert not hit & NEW_RULES and not hit & DETERMINISTIC_RULES
    # The /1 example carries no review_reference: the pre-existing known advisory.
    assert hit == {"REFERENCE_MISSING"}


def test_legal_example_package_with_reference_is_fully_clean(tmp_path):
    data = json.loads(EXAMPLE_PACKAGE.read_text(encoding="utf-8-sig"))
    data["lessons"][0]["exercises"][0]["review_reference"] = {"answer": "PC holds the address.", "criteria": ["正确"]}
    payload = payload_of(invoke_quality(write_json(tmp_path / "course.json", data)))
    assert payload["advisories"] == [] and payload["blocked"] is False
    assert payload["conclusion_summary"]["deterministic_error"] == {"count": 0, "rules": []}


# ---- §8.4 receipt binding flips to unbound after one byte change ----


def test_receipt_slots_flip_to_unbound_after_one_byte_change(tmp_path):
    path = write_json(tmp_path / "course.json", legal_course(package_id="receipt-binding"))
    package_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = write_json(
        tmp_path / "validation.json", {"package_sha256": package_hash, "result": {"ok": True, "valid": True}}
    )
    rendering = write_json(
        tmp_path / "rendering.json", {"package_sha256": package_hash, "result": {"ok": True}}
    )
    payload = payload_of(invoke_quality(path, "--validation-receipt", str(receipt), "--rendering-receipt", str(rendering)))
    assert payload["protocol_validation"] == "passed"
    assert payload["publication_gate"]["protocol"] == "passed"
    assert payload["publication_gate"]["rendering"] == "passed"
    raw = path.read_bytes()
    mutated = raw.replace(b"receipt-binding", b"receipt-bindinX", 1)
    assert mutated != raw and len(mutated) == len(raw)
    path.write_bytes(mutated)
    payload2 = payload_of(invoke_quality(path, "--validation-receipt", str(receipt), "--rendering-receipt", str(rendering)))
    assert payload2["package_sha256"] == hashlib.sha256(mutated).hexdigest() != package_hash
    assert payload2["protocol_validation"] == "unbound_receipt"
    assert payload2["publication_gate"]["protocol"] == "unbound_receipt"
    assert payload2["publication_gate"]["rendering"] == "unbound_receipt"
    assert payload2["publication_gate"]["writeback"] == "not_provided"


# ---- §3 error codes: DOCUMENT_UNREADABLE / INVALID_ARGUMENT ----


@pytest.mark.parametrize("value", ["0", "-5", "abc", "2.5", ""])
def test_invalid_long_section_chars_returns_invalid_argument(tmp_path, value):
    path = write_json(tmp_path / "course.json", legal_course())
    result = invoke_quality(path, "--long-section-chars", value)
    payload = error_payload_of(result)
    assert payload["error_code"] == "INVALID_ARGUMENT"
    assert payload["next_action"]


def test_missing_package_file_returns_document_unreadable(tmp_path):
    result = invoke_quality(tmp_path / "missing.json")
    payload = error_payload_of(result)
    assert payload["error_code"] == "DOCUMENT_UNREADABLE"
    assert payload["next_action"]


def test_undecodable_package_bytes_return_document_unreadable(tmp_path):
    path = tmp_path / "bad.bin"
    path.write_bytes(b"\xff\xfe\xfa")
    payload = error_payload_of(invoke_quality(path))
    assert payload["error_code"] == "DOCUMENT_UNREADABLE"


def test_broken_package_json_returns_invalid_argument(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{oops", encoding="utf-8")
    payload = error_payload_of(invoke_quality(path))
    assert payload["error_code"] == "INVALID_ARGUMENT"


def test_non_object_package_returns_invalid_argument(tmp_path):
    path = tmp_path / "array.json"
    path.write_text("[]", encoding="utf-8")
    payload = error_payload_of(invoke_quality(path))
    assert payload["error_code"] == "INVALID_ARGUMENT"


def test_broken_receipt_json_returns_invalid_argument(tmp_path):
    path = write_json(tmp_path / "course.json", legal_course())
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{oops", encoding="utf-8")
    payload = error_payload_of(invoke_quality(path, "--validation-receipt", str(receipt)))
    assert payload["error_code"] == "INVALID_ARGUMENT"


def test_missing_blueprint_file_returns_document_unreadable(tmp_path):
    path = write_json(tmp_path / "course.json", legal_course())
    payload = error_payload_of(invoke_quality(path, "--blueprint", str(tmp_path / "ghost.json")))
    assert payload["error_code"] == "DOCUMENT_UNREADABLE"


# ---- §8.6 read-only: runs without workspace or database ----


def test_quality_check_runs_without_workspace_or_database(monkeypatch, tmp_path):
    target = tmp_path / "no-workspace"
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(target))
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    monkeypatch.delenv("STUDYFLOW_DATABASE_PATH", raising=False)
    path = write_json(tmp_path / "course.json", legal_course())
    before = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
    payload = payload_of(invoke_quality(path))
    assert payload["ok"] is True
    assert not target.exists()
    assert {item.name: item.read_bytes() for item in tmp_path.iterdir()} == before


def test_quality_check_works_from_uninitialized_cwd(monkeypatch, tmp_path):
    import studyflow.infrastructure.config as config

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STUDYFLOW_WORKSPACE", raising=False)
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    monkeypatch.delenv("STUDYFLOW_DATABASE_PATH", raising=False)
    monkeypatch.setattr(config, "default_workspace_root", lambda: tmp_path / "default-ws")
    path = write_json(tmp_path / "course.json", legal_course())
    payload = payload_of(invoke_quality(path))
    assert payload["ok"] is True
    assert not (tmp_path / "default-ws").exists()
    assert sorted(item.name for item in tmp_path.iterdir()) == ["course.json"]


# ---- §2 capability discovery ----


def test_capabilities_expose_course_quality_check(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    monkeypatch.delenv("STUDYFLOW_DATABASE_PATH", raising=False)
    result = CliRunner().invoke(app, ["capabilities", "--format", "json"])
    assert result.exit_code == 0, result.output
    items = {item["name"]: item for item in json.loads(result.stdout)["capabilities"]}
    assert items["course_quality_check"]["kind"] == "read"
    assert "quality-check" in items["course_quality_check"]["command"]
