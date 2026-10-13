"""Author-declared pedagogical sequence, never an automatic grammar diagnosis."""
STAGES = ("vocabulary", "chunk", "pattern", "variation", "transfer")

def validate_progression(value, where):
    from studyflow.modules.courses.content import obj, ident, invalid
    obj(value, where, {"chain_id", "stage"}, {"chain_id", "stage"})
    ident(value["chain_id"], where+".chain_id")
    if value["stage"] not in STAGES: invalid(where+".stage", "未知递进阶段")

def validate_chains(data, *, required=False):
    from studyflow.modules.courses.content import invalid
    chains={}
    for lesson in data["lessons"]:
        for ex in lesson.get("exercises", []):
            value=ex.get("english", {}).get("progression")
            if not value:
                if required: invalid("english.progression", "补充课程的每项训练必须声明递进链和阶段")
                continue
            chain=chains.setdefault(value["chain_id"], [])
            chain.append(value["stage"])
    for identifier, stages in chains.items():
        if any(STAGES.index(a)>STAGES.index(b) for a,b in zip(stages,stages[1:])):
            invalid("progression."+identifier, "同一链必须按词汇、短语、句型、变式、迁移顺序编写")
        if required and (stages[0]!="vocabulary" or stages[-1]!="transfer" or "pattern" not in stages):
            invalid("progression."+identifier, "补充链需包含必要词汇、句型与最终迁移验证")
    if required and not chains: invalid("progression", "至少一条递进链")
    return list(chains)
