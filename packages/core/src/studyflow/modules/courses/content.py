"""Versioned, non-executable teaching content contract shared by CLI and readers."""
from __future__ import annotations
import json
import re
from copy import deepcopy
from pathlib import Path
from studyflow.shared.domain import DomainError, EXERCISE_TYPES
from studyflow.infrastructure.markdown import render_markdown, parse_front_matter

SCHEMA = "studyflow.course-package/1"
ENGLISH_SCHEMA = "studyflow.course-package/2"
DETAILS_SCHEMA = "studyflow.course-package/3"
PROGRESSION_SCHEMA = "studyflow.course-package/4"
STRUCTURED_SCHEMA = "studyflow.course-package/5"
BLOCK_TYPES = {"details", "concept", "comparison", "steps", "example", "callout", "summary", "practice"}
ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def invalid(where, message):
    raise DomainError("INVALID_COURSE_PACKAGE", f"{where}: {message}", "按 system.schema 与课程包契约修正课程包后重新校验；未写入课程。")


def obj(value, where, allowed, required=()):
    if not isinstance(value, dict): invalid(where, "需要对象")
    if set(value) - set(allowed): invalid(where, f"未知字段 {', '.join(sorted(set(value)-set(allowed)))}")
    if set(required) - set(value): invalid(where, f"缺少字段 {', '.join(sorted(set(required)-set(value)))}")
    return value


def text(value, where, limit=20000, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()): invalid(where, f"需要非空字符串，最多{limit}字符")
    return value


def ident(value, where):
    if not isinstance(value, str) or not ID.fullmatch(value): invalid(where, "id需小写字母开头，仅字母、数字、下划线、短横线，最多64字符")


def sequence(value, where, minimum=1, maximum=80):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum: invalid(where, f"需要{minimum}—{maximum}项列表")
    return value


def validate_lesson(lesson, where="lesson", english=False, details=False, progression=False, structured=False):
    obj(lesson, where, {"id", "title", "blocks", "exercises"}, {"id", "title", "blocks"})
    ident(lesson["id"], where+".id"); text(lesson["title"], where+".title", 200)
    exercises=sequence(lesson.get("exercises", []),where+".exercises",0,100)
    seen=set()
    for i,ex in enumerate(exercises):
        loc=f"{where}.exercises[{i}]"
        obj(ex,loc,{"id","title","prompt","requirements","type"}|({"review_reference"} if structured else set())|({"english"} if english else set()),{"id","title","prompt"}|({"english"} if english else set()))
        if "review_reference" in ex:
            from .references.contract import validate_reference
            validate_reference(ex["review_reference"],loc+".review_reference")
        if english:
            from studyflow.modules.courses.english.contract import validate_spec
            validate_spec(ex["english"],loc+".english",progression=progression)
        ident(ex["id"],loc+".id")
        if ex["id"] in seen: invalid(loc,"重复题目id")
        seen.add(ex["id"])
        text(ex["title"],loc+".title",200);text(ex["prompt"],loc+".prompt")
        text(ex.get("requirements",""),loc+".requirements",empty=True)
        if not isinstance(ex.get("type","SHORT_ANSWER"),str) or ex.get("type","SHORT_ANSWER") not in EXERCISE_TYPES: invalid(loc,"未知题目类型")
    bids=set()
    for i,b in enumerate(sequence(lesson["blocks"],where+".blocks")):
        loc=f"{where}.blocks[{i}]"
        if not isinstance(b,dict) or not isinstance(b.get("type"),str) or b.get("type") not in BLOCK_TYPES: invalid(loc,"未知内容块类型")
        kind=b["type"]
        if kind=="details" and not details: invalid(loc,"折叠详解需要课程包/3")
        extra={"details":{"summary","body"},"concept":{"body"},"comparison":{"columns","rows"},"steps":{"items"},"example":{"given","steps","conclusion"},"callout":{"body","tone"},"summary":{"items"},"practice":{"exercise_ids"}}[kind]
        required={"details":{"summary","body"},"concept":{"body"},"comparison":{"columns","rows"},"steps":{"items"},"example":{"given","steps","conclusion"},"callout":{"body"},"summary":{"items"},"practice":{"exercise_ids"}}[kind]
        if kind=="concept" and structured:
            extra=extra|{"sections"};required=set()
            if ("body" in b)==("sections" in b):invalid(loc,"concept必须二选一body或sections")
        obj(b,loc,{"id","type","title"}|extra,{"id","type","title"}|required)
        if "sections" in b:
            from .sections import validate_sections
            validate_sections(b["sections"],loc+".sections")
        ident(b["id"],loc+".id");text(b["title"],loc+".title",200)
        if b["id"] in bids: invalid(loc,"重复内容块id")
        bids.add(b["id"])
        if kind in {"concept","callout","details"} and "body" in b: text(b["body"],loc+".body")
        if kind=="details":text(b["summary"],loc+".summary",3000)
        if kind=="callout" and (not isinstance(b.get("tone","note"),str) or b.get("tone","note") not in {"note","warning","tip"}): invalid(loc,"未知提醒类型")
        if kind=="comparison":
            cols=sequence(b["columns"],loc+".columns",2,6)
            for col in cols: text(col,loc+".columns",200)
            for row in sequence(b["rows"],loc+".rows",1,50):
                sequence(row,loc+".rows",len(cols),len(cols))
                for cell in row:text(cell,loc+".cell",3000,empty=True)
        if kind in {"steps","example"}:
            for step in sequence(b["items" if kind=="steps" else "steps"],loc+".steps",1,20):
                obj(step,loc+".step",{"title","body"},{"title","body"});text(step["title"],loc,200);text(step["body"],loc)
        if kind=="example":text(b["given"],loc+".given");text(b["conclusion"],loc+".conclusion")
        if kind=="summary":
            for item in sequence(b["items"],loc+".items",1,20):text(item,loc,3000)
        if kind=="practice":
            refs=sequence(b["exercise_ids"],loc+".exercise_ids",1,100)
            for ref in refs:
                ident(ref,loc+".exercise_ids")
                if ref not in seen: invalid(loc,f"引用不存在的题目 {ref}")
            if len(set(refs))!=len(refs):invalid(loc,"重复题目引用")
    return lesson


def validate_package(data):
    obj(data,"package",{"schema","package_id","plan_line","course","lessons"},{"schema","package_id","plan_line","course","lessons"})
    if not isinstance(data["schema"],str) or data["schema"] not in {SCHEMA,ENGLISH_SCHEMA,DETAILS_SCHEMA,PROGRESSION_SCHEMA,STRUCTURED_SCHEMA}:invalid("schema","不支持的课程协议版本")
    ident(data["package_id"],"package_id");text(data["plan_line"],"plan_line",200)
    course=obj(data["course"],"course",{"title","summary","subject","difficulty"}|({"learning_mode"} if data["schema"] in {ENGLISH_SCHEMA,DETAILS_SCHEMA,PROGRESSION_SCHEMA,STRUCTURED_SCHEMA} else set()),{"title"})
    mode=course.get("learning_mode","general")
    if not isinstance(mode,str) or mode not in {"general","english"}:invalid("course.learning_mode","未知学习模式")
    text(course["title"],"course.title",200)
    for k,limit in [("summary",4000),("subject",120),("difficulty",32)]:text(course.get(k,""),"course."+k,limit,empty=True)
    ids=set()
    for i,lesson in enumerate(sequence(data["lessons"],"lessons",1,50)):
        validate_lesson(lesson,f"lessons[{i}]",english=mode=="english",details=data["schema"] in {DETAILS_SCHEMA,PROGRESSION_SCHEMA,STRUCTURED_SCHEMA},progression=data["schema"] in {PROGRESSION_SCHEMA,STRUCTURED_SCHEMA},structured=data["schema"]==STRUCTURED_SCHEMA)
        if mode=="english" and not lesson.get("exercises"):invalid("lessons","英语训练组至少一项训练")
        if lesson["id"] in ids:invalid("lessons","重复知识点id")
        ids.add(lesson["id"])
    if sum(len(lesson.get("exercises", [])) for lesson in data["lessons"]) > 500:
        invalid("lessons.exercises", "整课最多500道题")
    if data["schema"] in {PROGRESSION_SCHEMA,STRUCTURED_SCHEMA}:
        from .english.progression import validate_chains
        validate_chains(data)
    return data


def read_package(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size>4*1024*1024:invalid("file","课程包不存在或超过4MiB")
    def no_duplicates(pairs):
        out={}
        for k,v in pairs:
            if k in out:invalid("json",f"重复字段 {k}")
            out[k]=v
        return out
    try:data=json.loads(path.read_text(encoding="utf-8-sig"),object_pairs_hook=no_duplicates)
    except (ValueError,UnicodeError,OSError,RecursionError) as exc:invalid("file",f"JSON无法读取：{type(exc).__name__}")
    return validate_package(data)


def fallback_markdown(lesson):
    lines=["# "+lesson["title"]]
    for b in lesson["blocks"]:
        lines.append("## "+b["title"])
        kind=b["type"]
        if kind=="concept" and "sections" in b:
            from .sections import section_markdown
            lines.extend(section_markdown(b["sections"]))
        elif kind in {"concept","callout"}:lines.append(b["body"])
        elif kind=="details":lines.extend([b["summary"],"### 详解",b["body"]])
        elif kind=="comparison":
            def cell(v):return v.replace("|","\\|").replace("\n"," ")
            lines.extend(["| "+" | ".join(map(cell,b["columns"]))+" |","| "+" | ".join(["---"]*len(b["columns"]))+" |"])
            lines.extend("| "+" | ".join(map(cell,row))+" |" for row in b["rows"])
        elif kind in {"steps","example"}:
            if kind=="example":lines.extend(["### 已知条件",b["given"]])
            for n,s in enumerate(b["items" if kind=="steps" else "steps"],1):lines.extend([f"### {n}. {s['title']}",s["body"]])
            if kind=="example":lines.extend(["### 结论",b["conclusion"]])
        elif kind=="summary":lines.extend("- "+item for item in b["items"])
        else:
            titles={ex["id"]:ex["title"] for ex in lesson.get("exercises",[])}
            lines.extend("- "+titles[ref] for ref in b["exercise_ids"])
        lines.append("")
    return "\n\n".join(lines)+"\n"


def render_blocks(content, exercise_ids):
    if not content.startswith(("---\n","---\r\n")): return []
    meta,_=parse_front_matter(content)
    structured=meta.get("structured_lesson")
    if structured is None:return []
    if meta.get("content_schema") not in {SCHEMA,ENGLISH_SCHEMA,DETAILS_SCHEMA,PROGRESSION_SCHEMA,STRUCTURED_SCHEMA}:invalid("content_schema","不支持的组件版本")
    validate_lesson(structured,english=meta.get("learning_mode")=="english",details=meta.get("content_schema") in {DETAILS_SCHEMA,PROGRESSION_SCHEMA,STRUCTURED_SCHEMA},progression=meta.get("content_schema") in {PROGRESSION_SCHEMA,STRUCTURED_SCHEMA},structured=meta.get("content_schema")==STRUCTURED_SCHEMA)
    sources=structured.get("exercises",[])
    if len(sources)!=len(exercise_ids):invalid("exercises","源题目与已登记题目不一致，请导入新包")
    mapping={source["id"]:dbid for source,dbid in zip(sources,exercise_ids)}
    result=deepcopy(structured["blocks"])
    for b in result:
        if "sections" in b:
            from .sections import render_sections
            b["sections"]=render_sections(b["sections"])
        for key in ["body","given","conclusion","summary"]:
            if key in b:b[key+"_html"]=render_markdown(b[key])
        if b["type"] in {"steps","example"}:
            for step in b["items" if b["type"]=="steps" else "steps"]:step["body_html"]=render_markdown(step["body"])
        if b["type"]=="practice":b["exercise_ids"]=[mapping[ref] for ref in b["exercise_ids"]]
    return result
