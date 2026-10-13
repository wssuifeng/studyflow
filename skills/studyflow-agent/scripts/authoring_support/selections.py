from __future__ import annotations
import csv
import io
import json
import re
import tempfile
from pathlib import Path
from .paths import digest,sha
from .vocabulary import catalog


def validate_artifact(workspace,folder):
    folder=workspace.path(folder);manifest=workspace.json(folder/"manifest.json")
    if manifest.get("format")!=1 or not isinstance(manifest.get("files"),dict):
        raise ValueError("FORMAT: invalid selection manifest")
    if set(manifest["files"])!={"words.tsv","selection.json"}:
        raise ValueError("FORMAT: invalid selection artifacts")
    for name,expected in manifest["files"].items():
        target=workspace.path(folder/name)
        if not target.is_file() or sha(target)!=expected:
            raise ValueError("ARTIFACT_CHANGED: selected resource was edited outside its recipe")
    recipe=workspace.json(folder/"selection.json")
    if manifest.get("selection_hash")!=digest(recipe):
        raise ValueError("ARTIFACT_CHANGED: recipe hash differs from manifest")
    return manifest,recipe


def create(workspace,args):
    recipe=workspace.json(args.recipe)
    if recipe.get("format")!=1 or not re.fullmatch(r"[A-Za-z0-9-]{1,64}",recipe.get("selection_id","")) or type(recipe.get("revision")) is not int or recipe["revision"]<1:
        raise ValueError("FORMAT: selection_id and positive revision required")
    if any(not isinstance(recipe.get(key),str) or not recipe[key].strip() for key in ("stage_id","objective")):
        raise ValueError("FORMAT: finite stage and objective required")
    sources=recipe.get("sources");items=recipe.get("items")
    if not isinstance(sources,list) or not isinstance(items,list) or not 1<=len(items)<=60:
        raise ValueError("INPUT_BUDGET: explicit sources and 1..60 selected entries required")
    entries,current=catalog(workspace,[(s["id"],s["path"]) for s in sources])
    if [(s["id"],s["sha256"]) for s in sources]!=[(s["id"],s["sha256"]) for s in current]:
        raise ValueError("SOURCE_CHANGED: reread sources before selecting")
    by_id={e["entry_id"]:e for e in entries};selected=[];seen=set()
    for item in items:
        identifier=item.get("entry_id")
        if identifier in seen:raise ValueError("DUPLICATE_SELECTION: repeated source entry")
        seen.add(identifier)
        if identifier not in by_id:raise ValueError("ENTRY_NOT_FOUND: entry no longer exists in named sources")
        entry=by_id[identifier]
        if not entry["meaning"].strip():raise ValueError("MEANING_GAP: complete this relevant definition before ready selection")
        if item.get("meaning_verified") is not True:raise ValueError("REVIEW_REQUIRED: explicitly review the selected meaning")
        if item.get("role") not in {"new","prerequisite","review","family"} or any(not isinstance(item.get(k),str) or not item[k].strip() for k in ("sense","reason")):
            raise ValueError("FORMAT: entry role, selected sense and reason required")
        if not isinstance(item.get("evidence_refs",[]),list) or any(not isinstance(x,str) for x in item.get("evidence_refs",[])):
            raise ValueError("FORMAT: evidence_refs must be a list of locators")
        if item["role"]=="family" and not item.get("family_source_ref"):
            raise ValueError("REVIEW_REQUIRED: family relationship requires its source locator")
        selected.append((entry,item))
    stream=io.StringIO(newline="");writer=csv.writer(stream,delimiter="\t",lineterminator="\n")
    writer.writerow(["entry_id","word","phonetic","meaning","origin","role","sense","reason"])
    for entry,item in selected:writer.writerow([entry["entry_id"],entry["word"],entry["phonetic"],entry["meaning"],entry["origin"],item["role"],item["sense"],item["reason"]])
    words=stream.getvalue()
    if len(words)>12000:raise ValueError("OUTPUT_BUDGET: split by meaningful sub-objectives, do not trim definitions")
    folder=workspace.path(args.output);fingerprint=digest(recipe)
    result={"ok":True,"selection_hash":fingerprint,"entries":len(selected),"content_review":"author_attested_not_machine_certified","learning_mastery":"not_inferred"}
    if folder.exists():
        if not (folder/"manifest.json").is_file():raise ValueError("OUTPUT_EXISTS: unrecognized output already exists")
        manifest,_=validate_artifact(workspace,folder)
        if manifest["selection_hash"]!=fingerprint:raise ValueError("OUTPUT_EXISTS: immutable output belongs to another selection")
        return {**result,"created":False}
    folder.parent.mkdir(parents=True,exist_ok=True);workspace.path(folder.parent)
    stage=Path(tempfile.mkdtemp(prefix=".authoring-",dir=folder.parent));workspace.path(stage)
    try:
        (stage/"words.tsv").write_text(words,encoding="utf-8")
        (stage/"selection.json").write_text(json.dumps(recipe,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        manifest={"format":1,"selection_hash":fingerprint,"selection_id":recipe["selection_id"],"revision":recipe["revision"],"sources":current,"files":{name:sha(stage/name) for name in ("words.tsv","selection.json")}}
        (stage/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        workspace.path(folder)
        # Reserve the final directory exclusively. Publish the commit manifest last.
        # A concurrent empty target must never be replaced (POSIX rename would allow it).
        folder.mkdir(exist_ok=False)
        for name in ("words.tsv","selection.json","manifest.json"):
            target=workspace.path(folder/name)
            with target.open("xb") as out:
                out.write((stage/name).read_bytes())
    except BaseException:
        workspace.path(stage)
        for name in ("words.tsv","selection.json","manifest.json"):
            path=workspace.path(stage/name)
            if path.exists():path.unlink()
        stage.rmdir()
        raise
    for name in ("words.tsv","selection.json","manifest.json"):
        workspace.path(stage/name).unlink()
    workspace.path(stage).rmdir()
    return {**result,"created":True}


def selected_state(workspace, directory, sources):
    """Read immutable local views and links; never infer actual learning."""
    ids=set();stale=0;count=0;links=0;recipes=[];versions={}
    folder=workspace.path(directory);children=sorted(folder.iterdir()) if folder.exists() else []
    if len(children)>1000:raise ValueError("INPUT_BUDGET: narrow the explicit selections directory")
    hashes={s["id"]:s["sha256"] for s in sources}
    for child in children:
        if child.name.startswith(".authoring-"):continue
        workspace.path(child)
        if not child.is_dir() or not (child/"manifest.json").exists():continue
        manifest,recipe=validate_artifact(workspace,child);count+=1
        key=(recipe["selection_id"],recipe["revision"])
        if key in versions and versions[key]!=manifest["selection_hash"]:
            raise ValueError("SELECTION_VERSION_CONFLICT: same identity/revision has different content")
        versions[key]=manifest["selection_hash"];recipes.append(manifest["selection_hash"])
        for path in child.glob("course-link-*.json"):
            data=workspace.json(path);receipt=workspace.path(data["receipt_path"])
            if data.get("selection_hash")!=manifest["selection_hash"] or not receipt.is_file() or sha(receipt)!=data.get("receipt_sha256"):
                raise ValueError("RECEIPT_CHANGED: linked authoring receipt moved or changed")
            actual=workspace.json(receipt)
            course=actual.get("course",{})
            if actual.get("ok") is not True or course.get("id")!=data.get("course_id") or course.get("content_revision")!=data.get("content_revision"):
                raise ValueError("RECEIPT_MISMATCH: linked course identity/version changed")
            links+=1
        if any(hashes.get(s["id"])!=s["sha256"] for s in manifest["sources"]):stale+=1;continue
        ids.update(item["entry_id"] for item in recipe["items"])
    return {"ids":ids,"stale":stale,"versions":count,"links":links,"fingerprint":digest(sorted(recipes))}


def coverage(workspace,args):
    entries,sources=catalog(workspace,args.source)
    state=selected_state(workspace,args.selections_dir,sources);ids=state["ids"]
    if not ids.issubset({e["entry_id"] for e in entries}):raise ValueError("ENTRY_NOT_FOUND: invalid selection reference")
    return {"ok":True,"sources":[{**s,"selected":sum(e["entry_id"] in ids for e in entries if e["source_id"]==s["id"]),"remaining":s["records"]-sum(e["entry_id"] in ids for e in entries if e["source_id"]==s["id"])} for s in sources],"total_source_records":len(entries),"unique_spellings":len({e["word"] for e in entries}),"selection_versions":state["versions"],"linked_course_versions":state["links"],"stale_versions_excluded":state["stale"],"meaning_gaps":sum(not e["meaning"].strip() for e in entries),"learning_mastery":"not_inferred","coverage_kind":"current-source-resource-selection_not_learning"}


def link(workspace,args):
    folder=workspace.path(args.selection);manifest,_=validate_artifact(workspace,folder);receipt=workspace.json(args.receipt)
    course=receipt.get("course",{})
    if receipt.get("ok") is not True or course.get("id")!=args.course or type(course.get("content_revision")) is not int or course["content_revision"]!=args.content_revision:
        raise ValueError("RECEIPT_MISMATCH: use actual successful course detail with matching id/content_revision")
    payload={"format":1,"selection_hash":manifest["selection_hash"],"course_id":args.course,"content_revision":args.content_revision,"receipt_path":workspace.path(args.receipt).relative_to(workspace.root).as_posix(),"receipt_sha256":sha(workspace.path(args.receipt)),"learning_evidence":False,"verification":"matching_receipt_shape_not_authenticated_cli_origin"}
    target=workspace.path(folder/("course-link-"+digest([args.course,args.content_revision])[:24]+".json"))
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    if target.exists():
        if workspace.json(target)!=payload:raise ValueError("OUTPUT_EXISTS: conflicting receipt link")
        return {"ok":True,**payload,"replayed":True}
    with target.open("x",encoding="utf-8") as out:out.write(encoded)
    return {"ok":True,**payload,"replayed":False}
