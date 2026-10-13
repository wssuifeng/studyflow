"""Authoring helpers only touch synthetic material workspaces, never learner databases."""
from __future__ import annotations
import importlib
import json
from pathlib import Path
import subprocess
import sys
import shutil
import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "skills/studyflow-agent/scripts"
sys.path.insert(0, str(SCRIPTS))

@pytest.fixture
def tools():
    return importlib.import_module("authoring_support.cli")

@pytest.fixture
def materials(tmp_path):
    tmp_path=tmp_path/"author-materials"
    tmp_path.mkdir()
    (tmp_path / "base.tsv").write_text("word\t音标\t释义\t来源\nread\t\tv. 阅读\t词表\ndata\t\tn. 数据\t作者补充\n", encoding="utf-8")
    (tmp_path / "derived.tsv").write_text("word\t音标\t释义\t来源\nreader\t\tn. 读者\t词表\nreading\t\t\t待补\ndata\t\tn. 数据\t词表\n", encoding="utf-8")
    return tmp_path

def run(tools, root, *args):
    return tools.execute(["--root", str(root), *args])

def query(tools, root, *args):
    return run(tools, root, "query", "--source", "base=base.tsv", "--source", "derived=derived.tsv", *args)

def recipe(tools, root, word="read", revision=1):
    response=query(tools,root,"--word",word)
    row=response["items"][0]
    value={"format":1,"selection_id":"stage-reading","revision":revision,"stage_id":"S01","objective":"用一个已解释词义表达本次目标","sources":response["sources"],"items":[{"entry_id":row["entry_id"],"role":"new","sense":row["meaning"],"reason":"当前明确目标","meaning_verified":True,"evidence_refs":[]}]}
    path=root/"recipe.json";path.write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
    return value

def test_query_requires_purposeful_filter(tools, materials):
    with pytest.raises(ValueError,match="QUERY_REQUIRED"):
        query(tools,materials)

def test_bounded_query_and_cross_source_identity(tools, materials):
    response=query(tools,materials,"--word","data","--limit","1")
    assert len(response["items"])==1 and response["next_cursor"]
    second=query(tools,materials,"--word","data","--limit","1","--cursor",response["next_cursor"])
    assert second["items"][0]["entry_id"]!=response["items"][0]["entry_id"]
    assert second["next_cursor"] is None

def test_cursor_scope_and_source_changes_are_rejected(tools, materials):
    cursor=query(tools,materials,"--browse","--purpose","只检查当前候选","--limit","1")["next_cursor"]
    with pytest.raises(ValueError,match="CURSOR_MISMATCH"):
        query(tools,materials,"--word","data","--cursor",cursor)
    (materials/"base.tsv").write_text((materials/"base.tsv").read_text(encoding="utf-8")+"write\t\tv. 写\t词表\n",encoding="utf-8")
    with pytest.raises(ValueError,match="CURSOR_MISMATCH"):
        query(tools,materials,"--browse","--purpose","只检查当前候选","--limit","1","--cursor",cursor)

def test_identity_survives_source_reordering(tools, materials):
    before=query(tools,materials,"--word","read")["items"][0]["entry_id"]
    lines=(materials/"base.tsv").read_text(encoding="utf-8").splitlines()
    (materials/"base.tsv").write_text("\n".join([lines[0],*reversed(lines[1:])])+"\n",encoding="utf-8")
    assert query(tools,materials,"--word","read")["items"][0]["entry_id"]==before

@pytest.mark.parametrize("args",[("--limit","61"),("--max-chars","99"),("--browse",)])
def test_invalid_query_budgets(tools, materials, args):
    with pytest.raises(ValueError):query(tools,materials,*args)

def test_no_silent_truncation_of_large_entry(tools,materials):
    (materials/"base.tsv").write_text("word\t音标\t释义\t来源\nlarge\t\t"+"长"*6000+"\t词表\n",encoding="utf-8")
    with pytest.raises(ValueError,match="OUTPUT_BUDGET"):
        query(tools,materials,"--word","large","--max-chars","3000")

@pytest.mark.parametrize("relative",["../outside.tsv"])
def test_path_escape_rejected(tools,materials,relative):
    with pytest.raises(ValueError,match="PATH_BOUNDARY"):
        run(tools,materials,"query","--source","base="+relative,"--word","read")

def test_duplicate_source_and_rows_rejected(tools,materials):
    with pytest.raises(ValueError,match="SOURCE_ID"):
        run(tools,materials,"query","--source","base=base.tsv","--source","base=derived.tsv","--word","read")
    with (materials/"base.tsv").open("a",encoding="utf-8") as f:f.write("read\t\tv. 又读\t词表\n")
    with pytest.raises(ValueError,match="DUPLICATE_ENTRY"):query(tools,materials,"--word","read")

def test_symlink_rejected_if_supported(tools,materials,tmp_path):
    target=materials/"base.tsv";link=materials/"linked.tsv"
    try:link.symlink_to(target)
    except OSError:pytest.skip("OS does not allow creating a symlink in this test")
    with pytest.raises(ValueError,match="LINKED_PATH"):
        run(tools,materials,"query","--source","base=linked.tsv","--word","read")

def test_appdata_workspace_is_not_an_authoring_target(tools,materials):
    (materials/".studyflow").mkdir()
    with pytest.raises(ValueError,match="DATA_WORKSPACE"):
        query(tools,materials,"--word","read")

def test_selection_is_immutable_and_replay_safe(tools,materials):
    before=(materials/"base.tsv").read_bytes();value=recipe(tools,materials)
    result=run(tools,materials,"select","--recipe","recipe.json","--output","small/V001-r1")
    assert result["created"] and result["content_review"]=="author_attested_not_machine_certified"
    assert not run(tools,materials,"select","--recipe","recipe.json","--output","small/V001-r1")["created"]
    assert (materials/"base.tsv").read_bytes()==before
    assert "v. 阅读" in (materials/"small/V001-r1/words.tsv").read_text(encoding="utf-8")
    value["objective"]="不同目标";(materials/"recipe.json").write_text(json.dumps(value),encoding="utf-8")
    with pytest.raises(ValueError,match="OUTPUT_EXISTS"):
        run(tools,materials,"select","--recipe","recipe.json","--output","small/V001-r1")

@pytest.mark.parametrize("change,code",[("meaning_verified","REVIEW_REQUIRED"),("sources","SOURCE_CHANGED"),("duplicate","DUPLICATE_SELECTION"),("unknown","ENTRY_NOT_FOUND")])
def test_selection_requires_current_reviewed_sources(tools,materials,change,code):
    value=recipe(tools,materials)
    if change=="meaning_verified":value["items"][0][change]=False
    if change=="sources":value["sources"][0]["sha256"]="0"*64
    if change=="duplicate":value["items"]*=2
    if change=="unknown":value["items"][0]["entry_id"]="v-nonexistent"
    (materials/"recipe.json").write_text(json.dumps(value),encoding="utf-8")
    with pytest.raises(ValueError,match=code):
        run(tools,materials,"select","--recipe","recipe.json","--output","small/V001")
    assert not (materials/"small/V001").exists()

def test_missing_definition_cannot_be_selected_as_ready(tools,materials):
    recipe(tools,materials,"reading")
    with pytest.raises(ValueError,match="MEANING_GAP"):
        run(tools,materials,"select","--recipe","recipe.json","--output","small/gap")

def test_selection_scope_escape_rejected_before_writes(tools,materials):
    recipe(tools,materials)
    with pytest.raises(ValueError,match="PATH_BOUNDARY"):
        run(tools,materials,"select","--recipe","recipe.json","--output","../other-output")

def test_tampered_replay_refused(tools,materials):
    recipe(tools,materials);run(tools,materials,"select","--recipe","recipe.json","--output","small/V001")
    (materials/"small/V001/words.tsv").write_text("tampered",encoding="utf-8")
    with pytest.raises(ValueError,match="ARTIFACT_CHANGED"):
        run(tools,materials,"select","--recipe","recipe.json","--output","small/V001")

def test_coverage_is_resource_use_not_mastery(tools,materials):
    recipe(tools,materials);run(tools,materials,"select","--recipe","recipe.json","--output","small/V001")
    report=run(tools,materials,"coverage","--source","base=base.tsv","--source","derived=derived.tsv","--selections-dir","small")
    assert report["sources"][0]["selected"]==1 and report["sources"][0]["remaining"]==1
    assert report["total_source_records"]==5 and report["unique_spellings"]==4
    assert report["learning_mastery"]=="not_inferred" and "remaining_items" not in report

def test_cli_receipt_linking_is_scoped_and_not_learning(tools,materials):
    recipe(tools,materials);run(tools,materials,"select","--recipe","recipe.json","--output","small/V001")
    receipt={"ok":True,"course":{"id":"course-1","content_revision":3}}
    (materials/"receipt.json").write_text(json.dumps(receipt),encoding="utf-8")
    result=run(tools,materials,"link","--selection","small/V001","--receipt","receipt.json","--course","course-1","--content-revision","3")
    assert result["course_id"]=="course-1" and not result["learning_evidence"]
    assert run(tools,materials,"link","--selection","small/V001","--receipt","receipt.json","--course","course-1","--content-revision","3")["replayed"]
    with pytest.raises(ValueError,match="RECEIPT_MISMATCH"):
        run(tools,materials,"link","--selection","small/V001","--receipt","receipt.json","--course","other-course","--content-revision","3")

def governance_config(root):
    (root/"state.md").write_text("# 当前状态\n当前仅方案，不表明掌握。\n[阶段](stage.json)\n",encoding="utf-8")
    (root/"INDEX.md").write_text("[状态](state.md)\n",encoding="utf-8")
    (root/"stage.json").write_text(json.dumps({"stage_id":"S01","objectives":[{"id":"O1","evidence_refs":[]}],"exit_criteria":["独立检验"],"excluded":["下一阶段"],"next_stage":None}),encoding="utf-8")
    config={"format":1,"current_stage_id":"S01","state_file":"state.md","stage_file":"stage.json","index_file":"INDEX.md","max_chars":{}}
    (root/"governance.json").write_text(json.dumps(config),encoding="utf-8")
    return config

def test_governance_audit_is_read_only(tools,materials):
    governance_config(materials);before={p.name:p.read_bytes() for p in materials.iterdir() if p.is_file()}
    result=run(tools,materials,"audit","--config","governance.json")
    assert result["ok"] and result["content_quality"]=="not_evaluated" and result["learning_mastery"]=="not_inferred"
    assert before=={p.name:p.read_bytes() for p in materials.iterdir() if p.is_file()}

def test_governance_reports_stage_link_and_budget_problems(tools,materials):
    cfg=governance_config(materials);cfg["current_stage_id"]="S02";cfg["max_chars"]={"state.md":5}
    (materials/"governance.json").write_text(json.dumps(cfg),encoding="utf-8")
    (materials/"state.md").write_text("x"*30+"[缺失](missing.md)",encoding="utf-8")
    result=run(tools,materials,"audit","--config","governance.json")
    assert not result["ok"] and {i["code"] for i in result["issues"]}>={"STAGE_MISMATCH","SIZE_BUDGET","BROKEN_LINK"}

def test_standalone_copied_skill_without_repository(tools,materials,tmp_path):
    isolated=tmp_path/"copy";shutil.copytree(SCRIPTS,isolated,ignore=shutil.ignore_patterns("__pycache__"))
    process=subprocess.run([sys.executable,"-X","utf8",str(isolated/"authoring_workspace.py"),"--root",str(materials),"query","--source","base=base.tsv","--word","read"],capture_output=True,text=True,encoding="utf-8")
    assert process.returncode==0,process.stderr
    assert json.loads(process.stdout)["items"][0]["word"]=="read"


def test_json_error_exit_is_nonzero(materials):
    process=subprocess.run([sys.executable,"-X","utf8",str(SCRIPTS/"authoring_workspace.py"),"--root",str(materials),"query","--source","base=base.tsv"],capture_output=True,text=True,encoding="utf-8")
    assert process.returncode!=0
    assert json.loads(process.stdout)["ok"] is False


def test_unselected_browse_is_bounded_and_not_a_lesson_sequence(tools,materials):
    recipe(tools,materials);run(tools,materials,"select","--recipe","recipe.json","--output","small/V001")
    result=query(tools,materials,"--browse","--purpose","本阶段遗漏检查，不按返回顺序编课","--exclude-selections-dir","small","--limit","1")
    assert result["items"][0]["word"]!="read" and result["matched_records"]==4
    assert result["next_cursor"]


def test_source_drift_is_reported_not_silent_mastery(tools,materials):
    recipe(tools,materials);run(tools,materials,"select","--recipe","recipe.json","--output","small/V001")
    (materials/"base.tsv").write_text((materials/"base.tsv").read_text(encoding="utf-8").replace("阅读","读取"),encoding="utf-8")
    report=run(tools,materials,"coverage","--source","base=base.tsv","--source","derived=derived.tsv","--selections-dir","small")
    assert report["stale_versions_excluded"]==1 and report["sources"][0]["selected"]==0


def test_changed_receipt_does_not_remain_a_valid_usage_link(tools,materials):
    recipe(tools,materials);run(tools,materials,"select","--recipe","recipe.json","--output","small/V001")
    (materials/"receipt.json").write_text(json.dumps({"ok":True,"course":{"id":"c1","content_revision":1}}),encoding="utf-8")
    run(tools,materials,"link","--selection","small/V001","--receipt","receipt.json","--course","c1","--content-revision","1")
    (materials/"receipt.json").write_text("{}",encoding="utf-8")
    with pytest.raises(ValueError,match="RECEIPT_CHANGED"):
        run(tools,materials,"coverage","--source","base=base.tsv","--source","derived=derived.tsv","--selections-dir","small")


def test_helper_imports_no_database_runtime_and_bundle_skips_bytecode():
    for p in (SCRIPTS/"authoring_support").glob("*.py"):
        text=p.read_text(encoding="utf-8")
        assert "import sqlalchemy" not in text and "import sqlite3" not in text and "from studyflow" not in text
    bundler=(SCRIPTS.parents[2]/"apps/desktop/scripts/build-engine.ps1").read_text(encoding="utf-8-sig")
    assert "__pycache__" in bundler and '".pyc"' in bundler


def test_real_core_course_detail_matches_receipt_contract(tools,materials,app_service):
    recipe(tools,materials);run(tools,materials,"select","--recipe","recipe.json","--output","small/V001")
    app_service.seed_demo()
    course=app_service.list_courses()[0]
    response={"ok":True,**app_service.course_detail(course.id)}
    (materials/"real-core-receipt.json").write_text(json.dumps(response,ensure_ascii=False,default=str),encoding="utf-8")
    result=run(tools,materials,"link","--selection","small/V001","--receipt","real-core-receipt.json","--course",course.id,"--content-revision",str(response["course"]["content_revision"]))
    assert result["course_id"]==course.id


def test_source_query_does_not_create_full_partition(tools,materials):
    before=sorted(p.name for p in materials.iterdir())
    query(tools,materials,"--word","read")
    assert before==sorted(p.name for p in materials.iterdir())


def test_independent_source_cli_receipt_can_be_linked(tools,materials,app_service):
    import os
    recipe(tools,materials);run(tools,materials,"select","--recipe","recipe.json","--output","small/V001")
    app_service.seed_demo();course=app_service.list_courses()[0]
    env=os.environ.copy();env["STUDYFLOW_WORKSPACE"]=str(app_service.settings.workspace_root);env["STUDYFLOW_DATABASE_URL"]=app_service.settings.database_url
    env["PYTHONPATH"]=str(Path(__file__).resolve().parents[1]/"src")+os.pathsep+os.pathsep.join(p for p in sys.path if Path(p).name=="site-packages")
    process=subprocess.run([sys.executable,"-X","utf8","-m","studyflow","course","detail","--id",course.id,"--format","json"],env=env,capture_output=True,text=True,encoding="utf-8")
    assert process.returncode==0,process.stderr+process.stdout
    receipt=json.loads(process.stdout);assert receipt["ok"] is True
    (materials/"source-cli-receipt.json").write_text(process.stdout,encoding="utf-8")
    result=run(tools,materials,"link","--selection","small/V001","--receipt","source-cli-receipt.json","--course",course.id,"--content-revision",str(receipt["course"]["content_revision"]))
    assert result["course_id"]==course.id and not result["learning_evidence"]


def test_unicode_normalization_identity_collision_refused(tools,materials):
    (materials/"base.tsv").write_text("word\t音标\t释义\t来源\ncafé\t\tn. 咖啡\t词表\ncafe\u0301\t\tn. 咖啡\t词表\n",encoding="utf-8")
    with pytest.raises(ValueError,match="DUPLICATE_ENTRY"):query(tools,materials,"--word","café")


def test_unknown_output_directory_is_never_replaced(tools,materials):
    recipe(tools,materials);folder=materials/"small/existing";folder.mkdir(parents=True)
    with pytest.raises(ValueError,match="OUTPUT_EXISTS"):
        run(tools,materials,"select","--recipe","recipe.json","--output","small/existing")
    assert list(folder.iterdir())==[]


def test_junction_rejection_does_not_require_os_link_privileges(tools,materials,monkeypatch):
    from authoring_support.paths import Workspace
    def fake_link(self):return self.name=="base.tsv"
    monkeypatch.setattr(Path,"is_junction",fake_link,raising=False)
    root=Workspace(materials)
    with pytest.raises(ValueError,match="LINKED_PATH"):root.path("base.tsv")
