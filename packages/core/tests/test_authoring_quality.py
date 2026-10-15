import importlib.util,json
from pathlib import Path
P=Path(__file__).resolve().parents[3]/"skills/studyflow-agent/scripts/authoring_quality.py"
def tool():
 s=importlib.util.spec_from_file_location("quality",P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def course(english=False):
 q={"id":"q","prompt":"比较原理","review_reference":{"answer":"存储元件/原理对比；快慢","criteria":["正确"]}}
 if english:q["english"]={"target":"I do not read.","accepted_answers":["I don't read."],"sentence_parts":[]}
 return {"schema":"studyflow.course-package/6","course":{"learning_mode":"english" if english else "general"},"lessons":[{"id":"l","blocks":[{"id":"b","type":"concept","sections":[{"id":"s","title":"原理","role":"main","body":"完整定义。"*150}]}],"exercises":[q]}]}

def test_deterministic_advisories_do_not_claim_semantic_pass():
 m=tool();d=course();a=m.analyze(d,"a"*64);assert a==m.analyze(d,"a"*64)
 assert any(x["rule"]=="REFERENCE_PLACEHOLDER" for x in a["advisories"])
 assert any(x["rule"]=="LONG_SECTION_REVIEW" for x in a["advisories"])
 assert a["semantic_acceptance"]=="not_evaluated" and a["protocol_validation"]=="not_provided"
 assert not a["blocked"]

def test_multi_token_variants_empty_ipa_and_unknown_sources_are_not_hard_failures():
 m=tool();d=course(True);a=m.analyze(d,"a"*64)
 assert a["metrics"]["english_items"]==1 and a["metrics"]["annotated_phonetic_words"]==0
 assert a["source_verification"]=="not_provided"
 assert not a["blocked"]
 assert not any(x["rule"]=="VARIANT_TOKEN_COUNT" for x in a["advisories"])
 d["lessons"][0]["exercises"][0]["english"]["phonetic"]="/test/"
 assert m.analyze(d,"a"*64)["source_verification"]=="not_provided"

def test_exact_duplicate_does_not_pretend_to_measure_semantic_frames():
 m=tool();d=course(True);q=d["lessons"][0]["exercises"][0]
 q["english"]["accepted_answers"].append("I do not read.")
 a=m.analyze(d,"a"*64)
 assert any(x["rule"]=="DUPLICATE_VARIANT" for x in a["advisories"])
 assert "variant_equivalence" in a["manual_review_required"]
 assert a["metrics"]["semantic_frames"]=="not_inferred"

def test_cli_receipt_must_bind_the_input_hash():
 m=tool();d=course();a=m.analyze(d,"a"*64,receipt={"ok":True})
 assert a["protocol_validation"]=="unbound_receipt"
 a=m.analyze(d,"a"*64,receipt={"package_sha256":"a"*64,"result":{"ok":True}})
 assert a["protocol_validation"]=="passed"
