"""Deterministic advisory report. No database imports, no mutation of input courses."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata

RULE_VERSION = "authoring-quality/1"

def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split()).strip(".,!?;。！？")

def analyze(package, package_hash, *, blueprint=None, sources=None, receipt=None, related=None, long_section_chars=400):
    notes=[]
    metrics={"lessons":len(package.get("lessons",[])),"exercises":0,"sections":0,"english_items":0,"english_tokens":0,"annotated_words":0,"annotated_phonetic_words":0,"item_phonetics":0,"short_items_1_to_3_tokens":0,"declared_stages":{},"semantic_frames":"not_inferred"}
    targets=[];stage_counts=Counter();ids=set();teaching_ids=set()
    def warn(rule,path,evidence):notes.append({"rule":rule,"path":path,"evidence":evidence,"classification":"manual_review_candidate"})
    def sections(rows,path):
        for i,row in enumerate(rows):
            loc=f"{path}/{i}";metrics["sections"]+=1;teaching_ids.add(row.get("id"))
            if len(str(row.get("body","")))>long_section_chars:warn("LONG_SECTION_REVIEW",loc,{"characters":len(row["body"]),"threshold":long_section_chars,"action":"Review hierarchy, not automatic splitting"})
            sections(row.get("children",[]),loc+"/children")
    for li,lesson in enumerate(package.get("lessons",[])):
        lp=f"/lessons/{li}";titles=Counter()
        for bi,block in enumerate(lesson.get("blocks",[])):
            loc=f"{lp}/blocks/{bi}";teaching_ids.add(block.get("id"));titles[normalized(block.get("title",""))]+=1
            sections(block.get("sections",[]),loc+"/sections")
        for title,count in sorted(titles.items()):
            if title and count>1:warn("REPEATED_BLOCK_TITLE",lp,{"title":title,"count":count})
        for qi,q in enumerate(lesson.get("exercises",[])):
            loc=f"{lp}/exercises/{qi}";ids.add(q.get("id"));metrics["exercises"]+=1
            reference=q.get("review_reference",{});answer=str(reference.get("answer",""))
            if not answer.strip():warn("REFERENCE_MISSING",loc+"/review_reference",{"legacy_schema_may_allow_missing":True})
            elif re.search(r"TODO|TBD|待补|原理对比[；;]|^写出.{0,12}步骤$",answer,re.I):warn("REFERENCE_PLACEHOLDER",loc+"/review_reference/answer",{"excerpt":answer[:160]})
            visible=str(q.get("prompt",""))+"\n"+str(q.get("requirements",""))
            if len(normalized(answer))>=12 and normalized(answer) in normalized(visible):warn("POSSIBLE_ANSWER_LEAK",loc,{"reason":"Whole reference is present in learner-visible fields; inspect context"})
            numbers=re.findall(r"\d+(?:\.\d+)?",str(q.get("prompt","")))
            for bi,b in enumerate(lesson.get("blocks",[])):
                if b.get("type")=="example" and len(numbers)>1 and numbers==re.findall(r"\d+(?:\.\d+)?",str(b.get("given",""))):
                    warn("EXAMPLE_REHEARSAL_CANDIDATE",loc,{"example_path":f"{lp}/blocks/{bi}","shared_numbers":numbers,"not_a_semantic_verdict":True})
            e=q.get("english")
            if not e:continue
            metrics["english_items"]+=1;tokens=e.get("target","").split();metrics["english_tokens"]+=len(tokens);targets.append(normalized(e.get("target","")))
            metrics["short_items_1_to_3_tokens"]+=int(len(tokens)<=3)
            metrics["item_phonetics"]+=int(bool(e.get("phonetic","")))
            stage_counts[e.get("progression",{}).get("stage","undeclared")]+=1
            for part in e.get("sentence_parts",[]):
                for word in part.get("words",[]):
                    metrics["annotated_words"]+=1;metrics["annotated_phonetic_words"]+=int(bool(word.get("phonetic","")))
            values=[e.get("target",""),*e.get("accepted_answers",[])];seen=set()
            for vi,value in enumerate(values):
                value=normalized(value)
                if value in seen:warn("DUPLICATE_VARIANT",loc+"/english",{"variant_index":vi})
                seen.add(value)
    metrics["declared_stages"]=dict(sorted(stage_counts.items()))
    metrics["duplicate_targets"]={k:v for k,v in sorted(Counter(targets).items()) if v>1}
    metrics["short_item_denominator"]=metrics["english_items"]
    metrics["cross_course_exact_reuse"] = sorted(set(targets)&{normalized(q["english"]["target"]) for d in related or [] for l in d.get("lessons",[]) for q in l.get("exercises",[]) if q.get("english")})
    if blueprint:
        for i,obj in enumerate(blueprint.get("objectives",[])):
            missing=[x for x in obj.get("exercise_ids",[]) if x not in ids]
            missing_teaching=[x for x in obj.get("teaching_ids",[]) if x not in teaching_ids]
            if missing or missing_teaching:warn("BLUEPRINT_REFERENCE_MISSING",f"/blueprint/objectives/{i}",{"exercise_ids":missing,"teaching_ids":missing_teaching})
        metrics["declared_frames"]=blueprint.get("frames",[])
    validation="not_provided"
    if receipt:
        validation="unbound_receipt"
        if receipt.get("package_sha256")==package_hash:
            validation="passed" if receipt.get("result",{}).get("ok") is True else "failed"
    return {"report_schema":"studyflow.authoring-quality/1","rule_version":RULE_VERSION,"package_sha256":package_hash,"protocol_validation":validation,"source_verification":"declared_not_verified" if sources else "not_provided","blueprint_provided":bool(blueprint),"metrics":metrics,"advisories":notes,"manual_review_required":["fact_accuracy","teaching_alignment","variant_equivalence","phonetic_accuracy_and_license","real_rendering"],"semantic_acceptance":"not_evaluated","blocked":False,"unchecked_scope":["No live workspace queried","No schema validator reimplemented","Similarity is not semantic frame inference","Optional empty phonetics are not errors","No learner mastery evaluated"]}

def load(path):return json.loads(Path(path).read_text(encoding="utf-8-sig"))
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package",required=True,type=Path)
    parser.add_argument("--blueprint",type=Path);parser.add_argument("--sources",type=Path);parser.add_argument("--validation-receipt",type=Path)
    parser.add_argument("--related",action="append",default=[],type=Path);parser.add_argument("--long-section-chars",type=int,default=400)
    args=parser.parse_args()
    if args.long_section_chars<1:parser.error("threshold must be positive")
    raw=args.package.read_bytes()
    result=analyze(json.loads(raw.decode("utf-8-sig")),hashlib.sha256(raw).hexdigest(),blueprint=load(args.blueprint) if args.blueprint else None,sources=load(args.sources) if args.sources else None,receipt=load(args.validation_receipt) if args.validation_receipt else None,related=[load(p) for p in args.related],long_section_chars=args.long_section_chars)
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
if __name__=="__main__":main()
