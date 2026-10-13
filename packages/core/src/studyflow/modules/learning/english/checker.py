"""Deterministic full-answer checking; never combine tokens from distinct variants."""
import hashlib
import json
import re
import unicodedata

CHECKER_VERSION = "english-exact/1"

def tokenize(text):
    text=unicodedata.normalize("NFKC",text).replace("’", "'")
    return [word.strip('.,!?;:\"()[]') for word in text.split() if word.strip('.,!?;:\"()[]')]

def rule_hash(spec, prompt=""):
    relevant={k:spec.get(k,d) for k,d in [("target",""),("accepted_answers",[]),("case_sensitive",False),("evaluation_mode","local_exact")]}
    return hashlib.sha256(json.dumps({"spec":relevant,"prompt":prompt,"checker":spec.get("checker_version",CHECKER_VERSION)},ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def check_answer(spec, answer):
    if spec.get("checker_version",CHECKER_VERSION)!=CHECKER_VERSION:
        from studyflow.shared.domain import DomainError
        raise DomainError("ENGLISH_CHECKER_UNSUPPORTED","此冻结轮次的检查器版本暂不支持，未进行评分。")
    actual=tokenize(answer)
    variants=[spec["target"],*spec.get("accepted_answers",[])]
    normalize=(lambda v:v) if spec.get("case_sensitive",False) else str.casefold
    options=[]
    for variant in variants:
        target=tokenize(variant)
        differences=[{"index":i,"actual":actual[i] if i<len(actual) else "", "expected":target[i] if i<len(target) else ""}
          for i in range(max(len(actual),len(target))) if i>=len(actual) or i>=len(target) or normalize(actual[i])!=normalize(target[i])]
        options.append((differences,variant))
    differences,variant=min(options,key=lambda p:len(p[0]))
    return {"matched":not differences,"differences":differences,"matched_variant":variant if not differences else None,"checker_version":CHECKER_VERSION}
