import copy
import hashlib
import json

from studyflow.modules.courses.authoring_quality import RULE_VERSION, analyze

FIVE_CLASSES = {"deterministic_error", "content_defect", "review_required", "presentation_defect", "advisory"}


def course(english=False):
    q = {"id": "q", "prompt": "比较原理", "review_reference": {"answer": "存储元件/原理对比；快慢", "criteria": ["正确"]}}
    if english:
        q["english"] = {"target": "I do not read.", "accepted_answers": ["I don't read."], "sentence_parts": []}
    return {"schema": "studyflow.course-package/6", "course": {"learning_mode": "english" if english else "general"}, "lessons": [{"id": "l", "blocks": [{"id": "b", "type": "concept", "sections": [{"id": "s", "title": "原理", "role": "main", "body": "完整定义。" * 150}]}], "exercises": [q]}]}


def test_deterministic_advisories_do_not_claim_semantic_pass():
    d = course(); a = analyze(d, "a" * 64); assert a == analyze(d, "a" * 64)
    assert any(x["rule"] == "REFERENCE_PLACEHOLDER" for x in a["advisories"])
    assert any(x["rule"] == "LONG_SECTION_REVIEW" for x in a["advisories"])
    assert a["semantic_acceptance"] == "not_evaluated" and a["protocol_validation"] == "not_provided"
    assert not a["blocked"]


def test_multi_token_variants_empty_ipa_and_unknown_sources_are_not_hard_failures():
    d = course(True); a = analyze(d, "a" * 64)
    assert a["metrics"]["english_items"] == 1 and a["metrics"]["annotated_phonetic_words"] == 0
    assert a["source_verification"] == "not_provided"
    assert not a["blocked"]
    assert not any(x["rule"] == "VARIANT_TOKEN_COUNT" for x in a["advisories"])
    d["lessons"][0]["exercises"][0]["english"]["phonetic"] = "/test/"
    assert analyze(d, "a" * 64)["source_verification"] == "not_provided"


def test_exact_duplicate_does_not_pretend_to_measure_semantic_frames():
    d = course(True); q = d["lessons"][0]["exercises"][0]
    q["english"]["accepted_answers"].append("I do not read.")
    a = analyze(d, "a" * 64)
    assert any(x["rule"] == "DUPLICATE_VARIANT" for x in a["advisories"])
    assert "variant_equivalence" in a["manual_review_required"]
    assert a["metrics"]["semantic_frames"] == "not_inferred"


def test_cli_receipt_must_bind_the_input_hash():
    d = course(); a = analyze(d, "a" * 64, receipt={"ok": True})
    assert a["protocol_validation"] == "unbound_receipt"
    a = analyze(d, "a" * 64, receipt={"package_sha256": "a" * 64, "result": {"ok": True}})
    assert a["protocol_validation"] == "passed"


def test_chunk_clause_roles_are_review_candidates_not_grammar_verdicts():
    d = course(True); e = d['lessons'][0]['exercises'][0]['english']
    e.update(target='the size of the register', progression={'chain_id': 'a', 'stage': 'chunk'}, sentence_parts=[{'role': 'subject', 'start': 0, 'end': 5, 'words': [{'gloss': '寄存器', 'pos': 'n.'}] * 5}])
    r = analyze(d, 'a' * 64)
    assert any(x['rule'] == 'FRAGMENT_ROLE_CONTEXT_REVIEW' for x in r['advisories'])
    assert r['semantic_acceptance'] == 'not_evaluated' and not r['blocked']


def test_dictionary_dump_is_located_without_automatic_sense_selection():
    d = course(True); e = d['lessons'][0]['exercises'][0]['english']
    e['sentence_parts'] = [{'role': 'object', 'start': 0, 'end': 1, 'words': [{'gloss': 'n. 状态；国家；州 vt. 陈述', 'pos': 'n.'}]}]
    r = analyze(d, 'a' * 64)
    warning = next(x for x in r['advisories'] if x['rule'] == 'WORD_GLOSS_SENSE_REVIEW')
    assert warning['path'].endswith('/sentence_parts/0/words/0/gloss')
    assert e['sentence_parts'][0]['words'][0]['gloss'] == 'n. 状态；国家；州 vt. 陈述'


def test_missing_authored_phonetics_are_advisory_and_runtime_is_not_the_remedy():
    d = course(True); e = d['lessons'][0]['exercises'][0]['english']
    e['sentence_parts'] = [{'role': 'subject', 'start': 0, 'end': 1, 'words': [{'gloss': '我', 'pos': 'pron.'}]}]
    r = analyze(d, 'a' * 64)
    assert any(x['rule'] == 'AUTHOR_PHONETIC_REVIEW' for x in r['advisories'])
    assert not r['blocked']


def test_role_projection_exposes_wrong_boundaries_without_correcting_them():
    d = course(True); q = d['lessons'][0]['exercises'][0]
    q['prompt'] = '你可以用新名称保存该文件。'
    q['english'] = {'target': 'You can save the file with a new name.', 'progression': {'chain_id': 'a', 'stage': 'pattern'}, 'sentence_parts': [
        {'role': 'subject', 'start': 0, 'end': 2, 'words': [{'pos': 'pron.'}, {'pos': 'modal v.'}]},
        {'role': 'other', 'start': 2, 'end': 3, 'words': [{'pos': 'vt.'}]},
        {'role': 'predicate', 'start': 3, 'end': 4, 'words': [{'pos': 'det.'}]},
        {'role': 'object', 'start': 4, 'end': 6, 'words': [{'pos': 'n.'}, {'pos': 'prep.'}]},
        {'role': 'modifier', 'start': 6, 'end': 9, 'words': [{'pos': 'det.'}, {'pos': 'adj.'}, {'pos': 'n.'}]}]}
    r = analyze(d, 'a' * 64); row = r['english_structure_review'][0]
    assert [(p['role'], p['text']) for p in row['parts']] == [('subject', 'You can'), ('other', 'save'), ('predicate', 'the'), ('object', 'file with'), ('modifier', 'a new name.')]
    warnings = [x for x in r['advisories'] if x['rule'] == 'ROLE_POS_CONFLICT_REVIEW']
    assert len(warnings) == 3 and {x['evidence']['text'] for x in warnings} == {'You can', 'the', 'file with'}
    assert row['semantic_acceptance'] == 'not_evaluated' and r['semantic_acceptance'] == 'not_evaluated'
    assert q['english']['sentence_parts'][0]['end'] == 2


def test_correct_modal_predicate_and_complete_preposition_phrase_are_not_flagged():
    d = course(True); e = d['lessons'][0]['exercises'][0]['english']
    e.update(target='You can save the file with a new name.', progression={'chain_id': 'a', 'stage': 'pattern'}, sentence_parts=[
        {'role': 'subject', 'start': 0, 'end': 1, 'words': [{'pos': 'pron.'}]},
        {'role': 'predicate', 'start': 1, 'end': 3, 'words': [{'pos': 'aux.'}, {'pos': 'v.'}]},
        {'role': 'object', 'start': 3, 'end': 5, 'words': [{'pos': 'det.'}, {'pos': 'n.'}]},
        {'role': 'modifier', 'start': 5, 'end': 9, 'words': [{'pos': 'prep.'}, {'pos': 'det.'}, {'pos': 'adj.'}, {'pos': 'n.'}]}])
    r = analyze(d, 'a' * 64)
    assert not any(x['rule'] == 'ROLE_POS_CONFLICT_REVIEW' for x in r['advisories'])
    assert r['english_structure_review'][0]['parts'][3]['text'] == 'with a new name.'
    assert 'role_span_alignment' in r['manual_review_required']


def test_gap_filling_chunk_is_reported_for_independent_expression_review_not_auto_stemmed():
    d = course(True); q = d['lessons'][0]['exercises'][0]
    q['prompt'] = '在 The team ___. 中填入设计这个系统的部分。'
    q['english'].update(target='designs the system', progression={'chain_id': 'a', 'stage': 'chunk'}, sentence_parts=[])
    r = analyze(d, 'a' * 64)
    assert any(x['rule'] == 'FRAGMENT_INDEPENDENCE_REVIEW' for x in r['advisories'])
    assert q['english']['target'] == 'designs the system' and not r['blocked']
    assert 'independent_expression' in r['manual_review_required']


def test_chinese_and_unknown_pos_are_not_misread_as_nonverbal_predicates():
    d = course(True); e = d['lessons'][0]['exercises'][0]['english']
    for pos in ['动词', '系动词', '未知标签']:
        e.update(target='It is clear.', sentence_parts=[{'role': 'predicate', 'start': 1, 'end': 2, 'words': [{'pos': pos}]}])
        r = analyze(d, 'a' * 64)
        assert not any(x['rule'] == 'ROLE_POS_CONFLICT_REVIEW' for x in r['advisories'])


# ---- v2 schema, classification and new rules (design W1 §4/§5) ----


def test_report_schema_and_rule_version_are_upgraded():
    assert RULE_VERSION == "authoring-quality/4"
    a = analyze(course(), "a" * 64)
    assert a["report_schema"] == "studyflow.authoring-quality/2"


def test_every_advisory_carries_a_five_class_classification():
    d = course(True); d["lessons"][0]["exercises"][0]["english"]["accepted_answers"].append("I do not read.")
    r = analyze(d, "a" * 64)
    assert r["advisories"] and all(x["classification"] in FIVE_CLASSES for x in r["advisories"])
    by_rule = {x["rule"]: x["classification"] for x in r["advisories"]}
    assert by_rule["REFERENCE_PLACEHOLDER"] == "review_required"
    assert by_rule["DUPLICATE_VARIANT"] == "deterministic_error"
    a = analyze(course(), "a" * 64)
    assert {x["rule"]: x["classification"] for x in a["advisories"]}["LONG_SECTION_REVIEW"] == "advisory"


def test_duplicate_variant_is_a_deterministic_error_that_blocks():
    d = course(True); d["lessons"][0]["exercises"][0]["english"]["accepted_answers"].append("I do not read.")
    r = analyze(d, "a" * 64)
    dup = [x for x in r["advisories"] if x["rule"] == "DUPLICATE_VARIANT"]
    assert dup and dup[0]["classification"] == "deterministic_error"
    assert r["blocked"]
    assert "DUPLICATE_VARIANT" in r["conclusion_summary"]["deterministic_error"]["rules"]


def test_blueprint_reference_missing_is_a_deterministic_error():
    d = course(True)
    r = analyze(d, "a" * 64, blueprint={"objectives": [{"exercise_ids": ["ghost"], "teaching_ids": ["b"]}]})
    adv = [x for x in r["advisories"] if x["rule"] == "BLUEPRINT_REFERENCE_MISSING"]
    assert adv and adv[0]["classification"] == "deterministic_error"
    assert adv[0]["path"] == "/blueprint/objectives/0" and adv[0]["evidence"] == {"exercise_ids": ["ghost"], "teaching_ids": []}
    assert r["blocked"] and r["blueprint_provided"] and r["metrics"]["declared_frames"] == []


def test_unmapped_exercise_is_a_review_candidate():
    d = course(True)
    d["lessons"][0]["exercises"].append({"id": "q2", "prompt": "再读一遍", "review_reference": {"answer": "再读"}, "english": {"target": "I read."}})
    r = analyze(d, "a" * 64, blueprint={"objectives": [{"exercise_ids": ["q"], "teaching_ids": ["b"]}]})
    unmapped = [x for x in r["advisories"] if x["rule"] == "UNMAPPED_EXERCISE"]
    assert len(unmapped) == 1
    assert unmapped[0]["path"] == "/lessons/0/exercises/1" and unmapped[0]["evidence"]["exercise_id"] == "q2"
    assert unmapped[0]["classification"] == "review_required" and not r["blocked"]
    assert not any(x["rule"] == "UNMAPPED_EXERCISE" for x in analyze(d, "a" * 64)["advisories"])


def test_all_supplement_sections_raise_missing_main_section():
    d = course(True)
    d["lessons"][0]["blocks"][0]["sections"] = [{"id": "s1", "title": "补充", "role": "supplement", "body": "短"}]
    r = analyze(d, "a" * 64)
    adv = [x for x in r["advisories"] if x["rule"] == "MISSING_MAIN_SECTION"]
    assert len(adv) == 1
    assert adv[0]["path"] == "/lessons/0/blocks/0/sections" and adv[0]["evidence"]["roles"] == ["supplement"]
    assert adv[0]["classification"] == "review_required" and not r["blocked"]
    d2 = course(True)
    d2["lessons"][0]["blocks"][0]["sections"].append({"id": "s2", "title": "补充二", "role": "supplement", "body": "短"})
    assert not any(x["rule"] == "MISSING_MAIN_SECTION" for x in analyze(d2, "a" * 64)["advisories"])


def test_variant_structure_candidate_is_review_not_failure():
    d = course(True); r = analyze(d, "a" * 64)
    cand = [x for x in r["advisories"] if x["rule"] == "VARIANT_STRUCTURE_CANDIDATE"]
    assert len(cand) == 1
    assert cand[0]["evidence"]["reason"] == "token_count" and cand[0]["evidence"]["variant_index"] == 1
    assert cand[0]["classification"] == "review_required" and not r["blocked"]


def test_punctuation_only_variant_difference_is_a_structure_candidate():
    d = course(True); e = d["lessons"][0]["exercises"][0]["english"]
    e.update(target="send an e-mail", accepted_answers=["send an email"])
    r = analyze(d, "a" * 64)
    cand = [x for x in r["advisories"] if x["rule"] == "VARIANT_STRUCTURE_CANDIDATE"]
    assert len(cand) == 1 and cand[0]["evidence"]["reason"] == "punctuation_or_case"
    assert not any(x["rule"] == "DUPLICATE_VARIANT" for x in r["advisories"]) and not r["blocked"]


def test_exact_duplicate_does_not_also_raise_structure_candidate():
    d = course(True); d["lessons"][0]["exercises"][0]["english"]["accepted_answers"] = ["I do not read."]
    r = analyze(d, "a" * 64)
    assert any(x["rule"] == "DUPLICATE_VARIANT" for x in r["advisories"])
    assert not any(x["rule"] == "VARIANT_STRUCTURE_CANDIDATE" for x in r["advisories"])


def test_english_prompt_language_review_for_empty_or_same_language_prompts():
    d = course(True); d["lessons"][0]["exercises"][0]["prompt"] = "Translate the sentence."
    r = analyze(d, "a" * 64)
    adv = [x for x in r["advisories"] if x["rule"] == "ENGLISH_PROMPT_LANGUAGE_REVIEW"]
    assert len(adv) == 1
    assert adv[0]["path"] == "/lessons/0/exercises/0/prompt" and adv[0]["evidence"]["reason"] == "same_language_as_target"
    assert adv[0]["classification"] == "review_required" and not r["blocked"]
    d2 = course(True); d2["lessons"][0]["exercises"][0]["prompt"] = "  "
    adv2 = [x for x in analyze(d2, "a" * 64)["advisories"] if x["rule"] == "ENGLISH_PROMPT_LANGUAGE_REVIEW"]
    assert adv2 and adv2[0]["evidence"]["reason"] == "empty_prompt"
    assert not any(x["rule"] == "ENGLISH_PROMPT_LANGUAGE_REVIEW" for x in analyze(course(True), "a" * 64)["advisories"])


def test_near_template_candidate_uses_related_same_stage_same_tokens():
    d = course(True); e = d["lessons"][0]["exercises"][0]["english"]
    e.update(target="I like tea.", progression={"chain_id": "c", "stage": "vocabulary"})
    near = {"lessons": [{"id": "r", "exercises": [{"id": "r1", "english": {"target": "I like coffee.", "progression": {"chain_id": "c", "stage": "vocabulary"}}}]}]}
    far = {"lessons": [{"id": "r", "exercises": [{"id": "r2", "english": {"target": "You drink milk now.", "progression": {"chain_id": "c", "stage": "vocabulary"}}}]}]}
    r = analyze(d, "a" * 64, related=[near, far])
    adv = [x for x in r["advisories"] if x["rule"] == "NEAR_TEMPLATE_CANDIDATE"]
    assert len(adv) == 1
    assert adv[0]["evidence"]["related_target"] == "I like coffee." and adv[0]["evidence"]["stage"] == "vocabulary"
    assert adv[0]["classification"] == "review_required" and not r["blocked"]
    r2 = analyze(d, "a" * 64, related=[far])
    assert not any(x["rule"] == "NEAR_TEMPLATE_CANDIDATE" for x in r2["advisories"])
    assert r["metrics"]["cross_course_exact_reuse"] == []


def test_teaching_chain_list_outputs_stage_sequences_without_judgment():
    d = course(True); e = d["lessons"][0]["exercises"][0]["english"]
    e.update(target="I like tea.", progression={"chain_id": "likes", "stage": "vocabulary"})
    d["lessons"][0]["exercises"].append({"id": "q2", "prompt": "喜欢咖啡", "review_reference": {"answer": "喜欢"}, "english": {"target": "I like coffee.", "progression": {"chain_id": "likes", "stage": "chunk"}}})
    r = analyze(d, "a" * 64)
    chains = r["teaching_chain_list"]
    assert len(chains) == 1 and chains[0]["lesson_id"] == "l"
    chain = chains[0]["chains"][0]
    assert chain["chain_id"] == "likes" and chain["stage_sequence"] == ["vocabulary", "chunk"]
    assert chain["items"] == [{"exercise_id": "q", "stage": "vocabulary"}, {"exercise_id": "q2", "stage": "chunk"}]


def test_publication_gate_slots_bind_receipts_to_package_hash():
    d = course(True)
    r = analyze(d, "a" * 64)
    gate = r["publication_gate"]
    assert set(gate) == {"protocol", "content", "rendering", "writeback"}
    assert gate["protocol"] == "not_provided" and r["protocol_validation"] == "not_provided"
    assert gate["rendering"] == "not_provided" and gate["writeback"] == "not_provided"
    r = analyze(d, "a" * 64, receipt={"package_sha256": "b" * 64, "result": {"ok": True}})
    assert r["publication_gate"]["protocol"] == "unbound_receipt" and r["protocol_validation"] == "unbound_receipt"
    r = analyze(d, "a" * 64, receipt={"package_sha256": "a" * 64, "result": {"ok": True}}, rendering_receipt={"package_sha256": "a" * 64, "result": {"ok": True}})
    assert r["publication_gate"]["protocol"] == "passed" and r["publication_gate"]["rendering"] == "passed"
    r = analyze(d, "a" * 64, rendering_receipt={"package_sha256": "a" * 64, "result": {"ok": False}})
    assert r["publication_gate"]["rendering"] == "failed"
    r = analyze(d, "a" * 64, rendering_receipt={"package_sha256": "b" * 64, "result": {"ok": True}})
    assert r["publication_gate"]["rendering"] == "unbound_receipt"


def test_content_gate_slot_self_references_report_hash():
    d = course(True); r = analyze(d, "a" * 64)
    content = r["publication_gate"]["content"]
    assert content["status"] == "self_reference"
    gateless = copy.deepcopy(r)
    gateless["publication_gate"]["content"] = None
    canonical = json.dumps(gateless, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert content["report_sha256"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_conclusion_summary_capability_config_and_semantic_ids():
    d = course()
    r = analyze(d, "a" * 64, long_section_chars=200)
    summary = r["conclusion_summary"]
    assert set(summary) == FIVE_CLASSES
    assert sum(v["count"] for v in summary.values()) == len(r["advisories"])
    assert "REFERENCE_PLACEHOLDER" in summary["review_required"]["rules"]
    assert "LONG_SECTION_REVIEW" in summary["advisory"]["rules"]
    assert summary["deterministic_error"] == {"count": 0, "rules": []}
    assert r["capability_config"] == {"rule_version": RULE_VERSION, "options": {"long_section_chars": 200}}
    assert r["semantic_ids"] == {"package_id": None, "lesson_ids": ["l"], "exercise_ids": ["q"]}
    assert isinstance(r["checked_scope"], list) and r["checked_scope"]
    assert isinstance(r["unchecked_scope"], list) and r["unchecked_scope"]


def test_target_hashes_bind_target_and_variants():
    d = course(True); r = analyze(d, "a" * 64)
    hashes = r["target_hashes"]
    assert len(hashes) == 1 and hashes[0]["exercise_id"] == "q"
    assert hashes[0]["target_sha256"] == hashlib.sha256("I do not read.".encode("utf-8")).hexdigest()
    serialized = json.dumps(sorted(["I do not read.", "I don't read."]), ensure_ascii=False)
    assert hashes[0]["variants_sha256"] == hashlib.sha256(serialized.encode("utf-8")).hexdigest()
