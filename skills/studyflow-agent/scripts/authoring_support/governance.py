from __future__ import annotations
import re
from .paths import digest


def audit(workspace,args):
    cfg=workspace.json(args.config)
    if cfg.get("format")!=1 or not isinstance(cfg.get("current_stage_id"),str) or not cfg["current_stage_id"].strip():raise ValueError("FORMAT: governance format and explicit current stage required")
    issues=[];checked=[]
    def issue(code,path):issues.append({"code":code,"path":str(path)})
    paths={k:workspace.path(cfg[k]) for k in ("state_file","stage_file","index_file")}
    if len(set(paths.values()))!=3:raise ValueError("FORMAT: state/stage/index responsibilities must be explicit and distinct")
    budgets=cfg.get("max_chars",{})
    if not isinstance(budgets,dict) or any(type(v) is not int or v<1 for v in budgets.values()):raise ValueError("FORMAT: invalid character budgets")
    for key,path in paths.items():
        relative=path.relative_to(workspace.root).as_posix();checked.append(relative)
        if not path.is_file():issue("MISSING_ENTRY",relative);continue
        if path.stat().st_size>262144:issue("SIZE_BUDGET",relative);continue
        text=path.read_text(encoding="utf-8-sig");budget=budgets.get(relative,64000 if key=="stage_file" else 5000)
        if len(text)>budget:issue("SIZE_BUDGET",relative)
        if path.suffix.lower()==".md":
            for raw in re.findall(r"\[[^\]]*\]\(([^)]+)\)",text):
                target=raw.split("#",1)[0].strip().strip("<>")
                if not target or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://",target):continue
                resolved=workspace.path(path.parent/target)
                if not resolved.exists():issue("BROKEN_LINK",relative)
    stage_path=paths["stage_file"]
    if stage_path.is_file() and stage_path.stat().st_size<=262144:
        stage=workspace.json(stage_path)
        if stage.get("stage_id")!=cfg.get("current_stage_id"):issue("STAGE_MISMATCH",cfg["stage_file"])
        if not isinstance(stage.get("exit_criteria"),list) or not stage["exit_criteria"] or not isinstance(stage.get("excluded"),list) or "next_stage" not in stage:issue("FINITE_STAGE_REQUIRED",cfg["stage_file"])
        objectives=stage.get("objectives",[])
        if not isinstance(objectives,list) or not 1<=len(objectives)<=100:issue("OBJECTIVE_BUDGET",cfg["stage_file"])
        else:
            ids=[o.get("id") for o in objectives if isinstance(o,dict)]
            if len(ids)!=len(objectives) or any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)):issue("OBJECTIVE_ID",cfg["stage_file"])
    return {"ok":not issues,"issues":issues,"checked_paths":checked,"config_hash":digest(cfg),"writes":0,"content_quality":"not_evaluated","learning_mastery":"not_inferred","scope":"entry_links_budgets_finite_stage_only","semantic_state_consistency":"requires_agent_review"}
