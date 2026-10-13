"""English content extension to Exercise; v1 stays unchanged."""
from studyflow.shared.domain import DomainError
from studyflow.modules.learning.english.checker import tokenize

def validate_spec(spec, where="english", progression=False):
    from studyflow.modules.courses.content import obj,text,sequence,ident,invalid
    obj(spec,where,{"target","accepted_answers","evaluation_mode","case_sensitive","phonetic","gloss","explanation","objective_ids"}|({"progression"} if progression else set()),{"target"})
    text(spec["target"],where+".target",2000)
    tokens=tokenize(spec["target"])
    if not tokens or len(tokens)>80:invalid(where,"英语目标必须有1—80个可输入词位")
    if not isinstance(spec.get("evaluation_mode","local_exact"),str) or spec.get("evaluation_mode","local_exact") not in {"local_exact","agent"}:invalid(where,"未知评估方式")
    if "case_sensitive" in spec and not isinstance(spec["case_sensitive"],bool):invalid(where,"case_sensitive必须为布尔")
    for answer in sequence(spec.get("accepted_answers",[]),where+".accepted_answers",0,12):
        text(answer,where,2000)
        if len(tokenize(answer))!=len(tokens):invalid(where,"首版完整句变体必须有相同词位数；不同结构使用Agent模式")
    for k in ("phonetic","gloss","explanation"):text(spec.get(k,""),where+"."+k,4000,empty=True)
    tags=sequence(spec.get("objective_ids",[]),where+".objective_ids",0,20)
    for tag in tags:ident(tag,where+".objective_ids")
    if len(set(tags))!=len(tags):invalid(where,"重复目标标签")
    if "progression" in spec:
        from .progression import validate_progression
        validate_progression(spec["progression"], where+".progression")
    return spec
