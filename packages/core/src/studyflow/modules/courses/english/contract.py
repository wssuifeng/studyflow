"""English content extension to Exercise; v1 stays unchanged."""
from studyflow.shared.domain import DomainError
from studyflow.modules.learning.english.checker import tokenize

def validate_spec(spec, where="english", progression=False, training=False):
    from studyflow.modules.courses.content import obj,text,sequence,ident,invalid
    obj(spec,where,{"target","accepted_answers","evaluation_mode","case_sensitive","phonetic","gloss","explanation","objective_ids"}|({"progression"} if progression else set())|({"sentence_parts"} if training else set()),{"target"})
    text(spec["target"],where+".target",2000)
    tokens=tokenize(spec["target"])
    if not tokens or len(tokens)>80:invalid(where,"英语目标必须有1—80个可输入词位")
    if not isinstance(spec.get("evaluation_mode","local_exact"),str) or spec.get("evaluation_mode","local_exact") not in {"local_exact","agent"}:invalid(where,"未知评估方式")
    if "case_sensitive" in spec and not isinstance(spec["case_sensitive"],bool):invalid(where,"case_sensitive必须为布尔")
    for answer in sequence(spec.get("accepted_answers",[]),where+".accepted_answers",0,12):
        text(answer,where,2000)
        if not 1<=len(tokenize(answer))<=80:invalid(where,"变体必须有1—80个词位")
        if not training and len(tokenize(answer))!=len(tokens):invalid(where,"不同词位数完整变体需要课程包/6")
    for k in ("phonetic","gloss","explanation"):text(spec.get(k,""),where+"."+k,4000,empty=True)
    tags=sequence(spec.get("objective_ids",[]),where+".objective_ids",0,20)
    for tag in tags:ident(tag,where+".objective_ids")
    if len(set(tags))!=len(tags):invalid(where,"重复目标标签")
    if "progression" in spec:
        from .progression import validate_progression
        validate_progression(spec["progression"], where+".progression")
    if training and spec.get("evaluation_mode","local_exact")!="local_exact":invalid(where,"英语即时训练使用local_exact；可接受表达应预录完整accepted_answers")
    if "sentence_parts" in spec:
        cursor=0
        for i,part in enumerate(sequence(spec["sentence_parts"],where+".sentence_parts",1,20)):
            loc=f"{where}.sentence_parts[{i}]"
            obj(part,loc,{"role","start","end","words"},{"role","start","end","words"})
            if not isinstance(part["role"],str) or part["role"] not in {"subject","predicate","object","complement","modifier","other"}:invalid(loc,"未知句法角色")
            if any(isinstance(part[k],bool) or not isinstance(part[k],int) for k in ("start","end")) or part["start"]!=cursor or not cursor<part["end"]<=len(tokens):invalid(loc,"句法范围应连续覆盖目标词位")
            words=sequence(part["words"],loc+".words",part["end"]-cursor,part["end"]-cursor)
            for word in words:
                obj(word,loc+".words",{"phonetic","gloss","pos"})
                for k in ("phonetic","gloss","pos"):text(word.get(k,""),loc+"."+k,120,empty=True)
            cursor=part["end"]
        if cursor!=len(tokens):invalid(where,"句法范围未完整覆盖目标词位")
    return spec
