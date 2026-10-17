"""Authoring-quality report v2, the single Core implementation (W1 §2/§5).

Migrated rule-for-rule from ``skills/studyflow-agent/scripts/authoring_quality.py``:
the same input must produce the same rule/path/evidence for every migrated rule
and the same metrics (W1 §7). New §4 rules are deterministic triggers whose
semantic conclusions stay with human review. Report schema is
``studyflow.authoring-quality/2``: a superset of v1 that adds
``classification`` per advisory, ``conclusion_summary``, ``capability_config``,
``semantic_ids``, ``target_hashes``, ``checked_scope``, ``teaching_chain_list``
and the four-slot ``publication_gate``. Any provided receipt whose
``package_sha256`` differs from the analyzed package hash marks its slot
``unbound_receipt``; the writeback slot stays ``not_provided`` here because
readback receipts are produced by the separate readback check (§6).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from .chains import build_teaching_chain_list
from .rules import (
    CLASSIFICATIONS,
    FIVE_CLASSES,
    RULE_VERSION,
    has_main_section,
    near_template_matches,
    normalized,
    prompt_language_reason,
    section_tree_count,
    section_tree_roles,
    structural_key,
)

REPORT_SCHEMA = "studyflow.authoring-quality/2"


def _receipt_status(receipt, package_hash):
    """Binding semantics migrated from the v1 protocol_validation logic."""
    if not receipt:
        return "not_provided"
    if receipt.get("package_sha256") != package_hash:
        return "unbound_receipt"
    return "passed" if receipt.get("result", {}).get("ok") is True else "failed"


def _related_english_items(related):
    return [
        (q["english"]["target"], (q["english"].get("progression") or {}).get("stage"))
        for d in related or []
        for l in d.get("lessons", [])
        for q in l.get("exercises", [])
        if q.get("english")
    ]


def analyze(package, package_hash, *, blueprint=None, sources=None, receipt=None, related=None, long_section_chars=400, rendering_receipt=None):
    """Deterministic advisory analysis of one course package. No mutation of inputs."""
    notes = []
    structure_review = []
    metrics = {"lessons": len(package.get("lessons", [])), "exercises": 0, "sections": 0, "english_items": 0, "english_tokens": 0, "annotated_words": 0, "annotated_phonetic_words": 0, "item_phonetics": 0, "short_items_1_to_3_tokens": 0, "declared_stages": {}, "semantic_frames": "not_inferred"}
    targets = []
    stage_counts = Counter()
    ids = set()
    teaching_ids = set()
    exercise_locations = []
    target_hashes = []
    related_items = _related_english_items(related)

    def warn(rule, path, evidence):
        notes.append({"rule": rule, "path": path, "evidence": evidence, "classification": CLASSIFICATIONS[rule]})

    def sections(rows, path):
        for i, row in enumerate(rows):
            loc = f"{path}/{i}"
            metrics["sections"] += 1
            teaching_ids.add(row.get("id"))
            if len(str(row.get("body", ""))) > long_section_chars:
                warn("LONG_SECTION_REVIEW", loc, {"characters": len(row["body"]), "threshold": long_section_chars, "action": "Review hierarchy, not automatic splitting"})
            sections(row.get("children", []), loc + "/children")

    for li, lesson in enumerate(package.get("lessons", [])):
        lp = f"/lessons/{li}"
        titles = Counter()
        for bi, block in enumerate(lesson.get("blocks", [])):
            loc = f"{lp}/blocks/{bi}"
            teaching_ids.add(block.get("id"))
            titles[normalized(block.get("title", ""))] += 1
            block_sections = block.get("sections", [])
            sections(block_sections, loc + "/sections")
            if block_sections and not has_main_section(block_sections):
                warn("MISSING_MAIN_SECTION", loc + "/sections", {
                    "sections": section_tree_count(block_sections),
                    "roles": section_tree_roles(block_sections),
                    "action": "All sections are supplement/collapsed with no role=main backbone; review solvability, not a semantic verdict",
                })
        for title, count in sorted(titles.items()):
            if title and count > 1:
                warn("REPEATED_BLOCK_TITLE", lp, {"title": title, "count": count})
        for qi, q in enumerate(lesson.get("exercises", [])):
            loc = f"{lp}/exercises/{qi}"
            ids.add(q.get("id"))
            exercise_locations.append((loc, q.get("id")))
            metrics["exercises"] += 1
            reference = q.get("review_reference", {})
            answer = str(reference.get("answer", ""))
            if not answer.strip():
                warn("REFERENCE_MISSING", loc + "/review_reference", {"legacy_schema_may_allow_missing": True})
            elif re.search(r"TODO|TBD|待补|原理对比[；;]|^写出.{0,12}步骤$", answer, re.I):
                warn("REFERENCE_PLACEHOLDER", loc + "/review_reference/answer", {"excerpt": answer[:160]})
            visible = str(q.get("prompt", "")) + "\n" + str(q.get("requirements", ""))
            if len(normalized(answer)) >= 12 and normalized(answer) in normalized(visible):
                warn("POSSIBLE_ANSWER_LEAK", loc, {"reason": "Whole reference is present in learner-visible fields; inspect context"})
            numbers = re.findall(r"\d+(?:\.\d+)?", str(q.get("prompt", "")))
            for bi, b in enumerate(lesson.get("blocks", [])):
                if b.get("type") == "example" and len(numbers) > 1 and numbers == re.findall(r"\d+(?:\.\d+)?", str(b.get("given", ""))):
                    warn("EXAMPLE_REHEARSAL_CANDIDATE", loc, {"example_path": f"{lp}/blocks/{bi}", "shared_numbers": numbers, "not_a_semantic_verdict": True})
            e = q.get("english")
            if not e:
                continue
            metrics["english_items"] += 1
            tokens = e.get("target", "").split()
            metrics["english_tokens"] += len(tokens)
            targets.append(normalized(e.get("target", "")))
            metrics["short_items_1_to_3_tokens"] += int(len(tokens) <= 3)
            metrics["item_phonetics"] += int(bool(e.get("phonetic", "")))
            stage_counts[e.get("progression", {}).get("stage", "undeclared")] += 1
            stage = e.get("progression", {}).get("stage")
            parts = e.get("sentence_parts", [])
            language_reason = prompt_language_reason(q.get("prompt", ""))
            if language_reason:
                warn("ENGLISH_PROMPT_LANGUAGE_REVIEW", loc + "/prompt", {
                    "reason": language_reason,
                    "prompt_excerpt": str(q.get("prompt", ""))[:80],
                    "action": "English items need a distinct Chinese prompt; review empty or same-language prompts",
                })
            # Surface projection is an audit aid, not a second schema validator or grammar parser.
            # Show what the numeric ranges ACTUALLY select; full coverage alone cannot prove roles.
            projected = []
            for pi, part in enumerate(parts):
                start, end = part.get("start"), part.get("end")
                span = " ".join(tokens[start:end]) if isinstance(start, int) and isinstance(end, int) else ""
                labels = [str(w.get("pos", "")).strip().lower() for w in part.get("words", [])]
                projected.append({"role": part.get("role"), "start": start, "end": end, "text": span, "word_pos": labels})
                reason = None
                if part.get("role") == "subject" and any(re.search(r"\b(?:aux\.|modal\b)|助动词|情态动词", pos) for pos in labels):
                    reason = "A subject span includes an authored auxiliary/modal POS; inspect the actual clause boundary"
                elif part.get("role") == "predicate" and labels and all(labels) and all(re.search(r"\b(?:n|v|vt|vi|aux|adj|adv|prep|pron|det|conj)\.|\bmodal\b|动词|名词|形容词|副词|介词|代词|限定词|连词", pos) for pos in labels) and not any(re.search(r"\b(?:v|vt|vi|aux)\.|\bmodal\b|动词", pos) for pos in labels):
                    reason = "The predicate span has no authored verbal POS; verify both the role and POS"
                elif part.get("role") == "object" and labels and re.search(r"\bprep\.", labels[-1]):
                    reason = "The object span ends at an authored preposition; inspect whether a following phrase was cut"
                if reason:
                    warn("ROLE_POS_CONFLICT_REVIEW", f"{loc}/english/sentence_parts/{pi}", {"text": span, "role": part.get("role"), "authored_pos": labels, "action": reason, "not_a_grammar_verdict": True})
            structure_review.append({"exercise_id": q.get("id"), "path": loc, "prompt": q.get("prompt", ""), "target": e.get("target", ""), "stage": stage, "parts": projected, "semantic_acceptance": "not_evaluated"})
            if stage == "chunk" and re.search(r"_{2,}|＿{2,}", str(q.get("prompt", ""))):
                warn("FRAGMENT_INDEPENDENCE_REVIEW", loc + "/english/target", {"target": e.get("target", ""), "action": "Read the answer without its blank-filling carrier. Prefer a natural base-form phrase or a complete simple sentence; explicit contextual drills must not masquerade as independent expressions", "not_a_grammar_verdict": True})
            if stage in {"vocabulary", "chunk"} and any(p.get("role") != "other" for p in parts):
                warn("FRAGMENT_ROLE_CONTEXT_REVIEW", loc + "/english/sentence_parts", {"stage": stage, "action": "Distinguish phrase structure from clause function; supply the actual sentence context, not an inferred role"})
            missing_ipa = []
            for pi, part in enumerate(parts):
                for wi, word in enumerate(part.get("words", [])):
                    metrics["annotated_words"] += 1
                    metrics["annotated_phonetic_words"] += int(bool(str(word.get("phonetic", "")).strip()))
                    if not str(word.get("phonetic", "")).strip():
                        missing_ipa.append(part.get("start", 0) + wi)
                    gloss = str(word.get("gloss", ""))
                    pos_labels = re.findall(r"\b(?:n|v|vt|vi|adj|adv|prep|pron|det|conj)\.", gloss, re.I)
                    if len(gloss) > 48 or len(pos_labels) > 1 or len(re.findall(r"[;；]", gloss)) >= 3:
                        warn("WORD_GLOSS_SENSE_REVIEW", f"{loc}/english/sentence_parts/{pi}/words/{wi}/gloss", {"characters": len(gloss), "action": "Author one concise sense and POS for this context; do not select dictionary senses automatically"})
            if (parts and missing_ipa and not e.get("phonetic", "").strip()) or (not parts and not e.get("phonetic", "").strip()):
                warn("AUTHOR_PHONETIC_REVIEW", loc + "/english", {"missing_word_indices": missing_ipa, "action": "Author and verify phonetics with accent/context notes; runtime lookup is not a course-authoring substitute", "optional_in_protocol": True})
            values = [e.get("target", ""), *e.get("accepted_answers", [])]
            seen = set()
            for vi, value in enumerate(values):
                value = normalized(value)
                if value in seen:
                    warn("DUPLICATE_VARIANT", loc + "/english", {"variant_index": vi})
                seen.add(value)
            raw_target = str(e.get("target", ""))
            if raw_target.strip():
                for vi in range(1, len(values)):
                    target_tokens = raw_target.split()
                    variant_tokens = str(values[vi]).split()
                    reason = None
                    if len(variant_tokens) != len(target_tokens):
                        reason = "token_count"
                    elif structural_key(values[vi]) == structural_key(raw_target) and normalized(values[vi]) != normalized(raw_target):
                        reason = "punctuation_or_case"
                    if reason:
                        warn("VARIANT_STRUCTURE_CANDIDATE", loc + "/english", {
                            "variant_index": vi,
                            "reason": reason,
                            "target_tokens": len(target_tokens),
                            "variant_tokens": len(variant_tokens),
                            "action": "Review whether this structural difference keeps the variant equivalent to the target; not a semantic verdict",
                        })
            for evidence in near_template_matches(e.get("target", ""), stage, related_items):
                warn("NEAR_TEMPLATE_CANDIDATE", loc, evidence)
            hash_values = [raw_target, *[str(v) for v in e.get("accepted_answers", [])]]
            target_hashes.append({
                "exercise_id": q.get("id"),
                "target_sha256": hashlib.sha256(raw_target.encode("utf-8")).hexdigest(),
                "variants_sha256": hashlib.sha256(json.dumps(sorted(hash_values), ensure_ascii=False).encode("utf-8")).hexdigest(),
            })
    metrics["declared_stages"] = dict(sorted(stage_counts.items()))
    metrics["duplicate_targets"] = {k: v for k, v in sorted(Counter(targets).items()) if v > 1}
    metrics["short_item_denominator"] = metrics["english_items"]
    metrics["cross_course_exact_reuse"] = sorted(set(targets) & {normalized(q["english"]["target"]) for d in related or [] for l in d.get("lessons", []) for q in l.get("exercises", []) if q.get("english")})
    if blueprint:
        referenced = set()
        for i, obj in enumerate(blueprint.get("objectives", [])):
            missing = [x for x in obj.get("exercise_ids", []) if x not in ids]
            missing_teaching = [x for x in obj.get("teaching_ids", []) if x not in teaching_ids]
            referenced.update(obj.get("exercise_ids", []))
            if missing or missing_teaching:
                warn("BLUEPRINT_REFERENCE_MISSING", f"/blueprint/objectives/{i}", {"exercise_ids": missing, "teaching_ids": missing_teaching})
        for loc, exercise_id in exercise_locations:
            if exercise_id not in referenced:
                warn("UNMAPPED_EXERCISE", loc, {
                    "exercise_id": exercise_id,
                    "action": "No blueprint objective references this exercise; confirm placement or extend the blueprint",
                })
        metrics["declared_frames"] = blueprint.get("frames", [])
    validation = _receipt_status(receipt, package_hash)
    rendering = _receipt_status(rendering_receipt, package_hash)
    conclusion_summary = {cls: {"count": 0, "rules": []} for cls in FIVE_CLASSES}
    class_counts = Counter()
    class_rules = {}
    for advisory in notes:
        cls = advisory["classification"]
        class_counts[cls] += 1
        class_rules.setdefault(cls, set()).add(advisory["rule"])
    for cls in FIVE_CLASSES:
        conclusion_summary[cls] = {"count": class_counts.get(cls, 0), "rules": sorted(class_rules.get(cls, set()))}
    checked_scope = [
        "Deterministic structural and lexical triggers only; semantic conclusions stay with human review",
        "Reference answer presence, placeholder patterns and whole-answer leak in learner-visible fields",
        "Variant duplicate normalization plus punctuation/case and token-count structure candidates",
        "Section hierarchy length threshold and main/supplement composition",
        "English role projection with authored POS, gloss senses, authored phonetics and prompt language",
        "Receipt binding of every provided slot to the package SHA-256",
    ]
    if blueprint:
        checked_scope.append("Blueprint objective references and exercise mapping")
    if related:
        checked_scope.append("Cross-course exact reuse and near-template candidates against related packages")
    report = {
        "report_schema": REPORT_SCHEMA,
        "rule_version": RULE_VERSION,
        "package_sha256": package_hash,
        "protocol_validation": validation,
        "source_verification": "declared_not_verified" if sources else "not_provided",
        "blueprint_provided": bool(blueprint),
        "metrics": metrics,
        "advisories": notes,
        "english_structure_review": structure_review,
        "teaching_chain_list": build_teaching_chain_list(package),
        "conclusion_summary": conclusion_summary,
        "capability_config": {"rule_version": RULE_VERSION, "options": {"long_section_chars": long_section_chars}},
        "semantic_ids": {
            "package_id": package.get("package_id"),
            "lesson_ids": [lesson.get("id") for lesson in package.get("lessons", [])],
            "exercise_ids": [exercise_id for _, exercise_id in exercise_locations],
        },
        "target_hashes": target_hashes,
        "checked_scope": checked_scope,
        "publication_gate": {"protocol": validation, "content": None, "rendering": rendering, "writeback": "not_provided"},
        "manual_review_required": ["fact_accuracy", "teaching_alignment", "variant_equivalence", "phonetic_accuracy_and_license", "real_rendering", "role_span_alignment", "independent_expression"],
        "semantic_acceptance": "not_evaluated",
        "blocked": any(advisory["classification"] == "deterministic_error" for advisory in notes),
        "unchecked_scope": ["No live workspace queried", "No schema validator reimplemented", "Similarity is not semantic frame inference", "Optional empty phonetics are not errors", "No learner mastery evaluated"],
    }
    # Content slot: self-reference to this report's hash. The value is the
    # SHA-256 of the whole report serialized with publication_gate.content set
    # to null (json.dumps sort_keys=True, ensure_ascii=False, separators
    # (",", ":")); a verifier reconstructs it by the same convention.
    report["publication_gate"]["content"] = {
        "status": "self_reference",
        "report_sha256": hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "reconstruction": "SHA-256 of this report serialized with publication_gate.content=null (json.dumps sort_keys=True, ensure_ascii=False, separators=(',',':'))",
    }
    return report
