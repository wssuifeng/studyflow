"""Immutable provenance verification and lossless legacy projection."""
from __future__ import annotations
import json
import hashlib
from html.parser import HTMLParser
from sqlalchemy import select
from studyflow.modules.courses.models import Course, Lesson
from studyflow.modules.planning.models import PlanCourseItem
from studyflow.modules.learning.models import CourseStudySession, PlanNotebookSource
from studyflow.shared.domain import DomainError
from .document import identity, invalid, normalize


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts = []
    def handle_data(self, data): self.parts.append(data)
    def handle_endtag(self, tag):
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr", "pre"}: self.parts.append("\n")
    def handle_starttag(self, tag, attrs):
        if tag == "br": self.parts.append("\n")


def plain_html(html):
    parser = PlainText(); parser.feed(html)
    return normalize("".join(parser.parts))


def membership(db, pid, cid, lid, scope):
    if scope not in {"PLAN", "COURSE", "LESSON"}: invalid("笔记归属无效。")
    if scope == "PLAN":
        if cid or lid: invalid("计划级记录不能附带课程或知识点。")
        return {"course_id": None, "lesson_id": None, "scope": scope, "course_title": None, "lesson_title": None}
    identity(cid, "课程ID")
    course = db.get(Course, cid)
    belongs = course and (course.plan_line_id == pid or db.scalar(select(PlanCourseItem.id).where(PlanCourseItem.plan_line_id == pid, PlanCourseItem.course_id == cid)))
    if not belongs: invalid("目标课程不属于此计划。")
    lesson = db.get(Lesson, lid) if isinstance(lid, str) else None
    if scope == "LESSON" and (not lesson or lesson.course_id != cid): invalid("目标知识点不属于此课程。")
    if scope == "COURSE" and lid: invalid("课程级记录不能附带知识点。")
    return {"scope": scope, "course_id": cid, "lesson_id": lid, "course_title": course.title, "lesson_title": lesson.title if lesson else None}


def verify(db, pid, item):
    if not isinstance(item, dict) or set(item) - {"id", "original", "course_id", "lesson_id", "source_study_id", "source_block_id", "source_section_id"}: invalid("出处包含未知字段。")
    identity(item.get("id"), "出处ID")
    original = item.get("original")
    if not isinstance(original, str) or not original.strip() or len(original) > 20000: invalid("出处摘录长度无效。")
    cid, lid, sid = item.get("course_id"), item.get("lesson_id"), item.get("source_study_id")
    # A live lesson can disappear; the frozen snapshot remains authoritative.
    membership(db, pid, cid, None, "COURSE")
    study = db.get(CourseStudySession, sid) if isinstance(sid, str) else None
    if not study or study.course_id != cid: invalid("冻结学习轮次不存在或不属于此课程。")
    snapshot = json.loads(study.snapshot_json)
    lesson = next((l for l in snapshot["lessons"] if l["id"] == lid), None)
    if not lesson: invalid("冻结知识点不存在。")
    html = lesson.get("rendered_html", "")
    block_id = item.get("source_block_id")
    if block_id:
        from studyflow.modules.courses.content import fallback_markdown
        from studyflow.infrastructure.markdown import render_markdown
        block = next((b for b in lesson.get("content_blocks", []) if b["id"] == block_id), None)
        if not block or block["type"] == "practice": invalid("出处内容块无效。")
        html = render_markdown(fallback_markdown({"title": "", "blocks": [block]}))
    section_id=item.get("source_section_id")
    if section_id:
        from studyflow.modules.courses.sections import find_section,section_markdown
        if not block_id:invalid("小节出处需要所属内容块。")
        section=find_section(block.get("sections",[]),section_id)
        if not section:invalid("引用小节不在指定冻结正文中。")
        html=render_markdown("\n\n".join(section_markdown([section])))
    valid = normalize(original) in plain_html(html)
    if not valid and not block_id and snapshot["course"].get("learning_mode") == "english":
        valid = any(normalize(original) == normalize(ex.get("english", {}).get("target", "")) for ex in lesson.get("exercises", []))
    if not valid: invalid("摘录不在指定冻结正文中。")
    return {**item, "course_title": snapshot["course"]["title"], "lesson_title": lesson["title"], "content_hash": study.content_hash, "verification": "VERIFIED"}


def load(db, row):
    if not row: return {}
    return {s.id: json.loads(s.data_json) for s in db.scalars(select(PlanNotebookSource).where(PlanNotebookSource.notebook_id == row.id))}


def legacy(db, pid, blocks):
    entries = []; sources = {}
    for b in blocks:
        content = []
        if b.get("quote"):
            sid = "legacy-" + hashlib.sha256(b["id"].encode()).hexdigest()[:40]
            item = {"id": sid, "original": b["quote"], "course_id": b.get("course_id"), "lesson_id": b.get("lesson_id"), "source_study_id": b.get("source_study_id")}
            if b.get("source_block_id"): item["source_block_id"] = b["source_block_id"]
            try: sources[sid] = verify(db, pid, item)
            except DomainError:
                sources[sid] = {**item, "course_title": b.get("course_title"), "lesson_title": b.get("lesson_title"), "content_hash": b.get("content_hash"), "verification": "LEGACY_UNVERIFIED"}
            content.append({"type": "paragraph", "content": [{"type": "text", "text": b["quote"], "marks": [{"type": "citation", "attrs": {"sourceId": sid, "occurrenceId": "legacy-" + hashlib.sha256(b["id"].encode()).hexdigest()[:40]}}]}]})
        if b.get("text"):
            content.append({"type": "paragraph", "content": [{"type": "text", "text": b["text"]}]})
        entries.append({"id": b["id"], "scope": b.get("scope", "LESSON" if b.get("lesson_id") else "COURSE" if b.get("course_id") else "PLAN"), "course_id": b.get("course_id"), "lesson_id": b.get("lesson_id"), "course_title": b.get("course_title"), "lesson_title": b.get("lesson_title"), "content": content or [{"type": "paragraph"}]})
    return entries, sources
