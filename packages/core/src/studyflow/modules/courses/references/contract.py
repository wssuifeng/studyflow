import hashlib
import json

def fingerprint(exercise):
    english=dict(exercise.get("english") or {})
    english.pop("checker_version",None)
    payload={"prompt":exercise["prompt"],"requirements":exercise.get("requirements",""),"type":exercise.get("type","SHORT_ANSWER"),"english":english}
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def reference_hash(reference,question_hash):
    return hashlib.sha256(json.dumps({"reference":reference,"question_hash":question_hash},ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def validate_reference(value,where):
    from ..content import obj,text,sequence
    obj(value,where,{"answer","explanation","criteria","accepted_variants","source"},{"answer","explanation","criteria"})
    for key in ("answer","explanation"):text(value[key],where+"."+key,20000)
    for key in ("criteria","accepted_variants"):
        if key in value:
            for item in sequence(value[key],where+"."+key,0 if key=="accepted_variants" else 1,30):text(item,where+"."+key,3000)
    if "source" in value:text(value["source"],where+".source",3000)
