"""Shared read models for CLI and Engine; no database or filesystem access."""
from .markdown import render_markdown


def submission_summary(row):
    return {"id": row.id, "exercise_id": row.exercise_id, "task_id": row.task_id,
            "parent_submission_id": row.parent_submission_id, "status": row.status,
            "version": row.version, "attempt_number": row.attempt_number,
            "attempt_kind": row.attempt_kind, "next_action": row.next_action}


def course_summary(row):
    schedule = getattr(row, "schedule_item", None)
    return {"id": row.id, "title": row.title, "summary": row.summary,
            "subject": row.subject, "content_type": row.content_type,
            "difficulty": row.difficulty, "source_type": row.source_type,
            "plan_line": row.plan_line.name if row.plan_line else None,
            "plan_line_id": row.plan_line_id, "status": row.status,
            "sequence": getattr(row, "plan_sequence", None), "total": getattr(row, "plan_total", 0),
            "knowledge_total": getattr(row, "knowledge_total", len(row.lessons)),
            "knowledge_completed": getattr(row, "knowledge_completed", 0),
            "exercise_total": getattr(row, "exercise_total", 0),
            "exercise_completed": getattr(row, "exercise_completed", 0),
            "progress_percent": getattr(row, "progress_percent", 0),
            "planned_start": getattr(row, "planned_start", None),
            "planned_end": getattr(row, "planned_end", None),
            "schedule": {"date": schedule.scheduled_date, "start_time": schedule.start_time,
                         "end_time": schedule.end_time, "status": schedule.status} if schedule else None}


def course_detail(row):
    lessons = []
    for lesson in row.lessons:
        progress = getattr(lesson, "learning_progress", None)
        lessons.append({
            "id": lesson.id, "title": lesson.title, "position": lesson.position,
            "markdown_path": lesson.markdown_path, "summary": lesson.summary,
            "document_status": getattr(lesson, "document_status", "UNKNOWN"),
            "rendered_html": getattr(lesson, "rendered_html", ""),
            "progress": {"progress_percent": progress.progress_percent, "status": progress.status,
                         "last_position": progress.last_position} if progress else
                        {"progress_percent": 0, "status": "NOT_STARTED", "last_position": ""},
            "exercises": [{
                "id": ex.id, "title": ex.title, "prompt": ex.prompt, "requirements": ex.requirements,
                "type": ex.exercise_type, "position": ex.position,
                "latest_submission": submission_summary(ex.latest_submission) if getattr(ex, "latest_submission", None) else None,
                "draft": submission_summary(ex.draft) if getattr(ex, "draft", None) else None,
            } for ex in lesson.exercises],
        })
    result = course_summary(row)
    result["reading_percent"] = round(sum(item["progress"]["progress_percent"] for item in lessons) / len(lessons)) if lessons else 0
    last = max((item for item in row.lessons if getattr(item, "learning_progress", None)),
               key=lambda item: item.learning_progress.updated_at or item.learning_progress.created_at, default=None)
    return {"course": result, "lessons": lessons, "resume_lesson_id": last.id if last else None,
            "next_action": "按顺序阅读知识点并完成练习；阅读进度与练习通过状态分别记录。"}


def submission_detail(row):
    exercise = row.exercise
    lesson = exercise.lesson
    course = lesson.course
    return {
        **submission_summary(row), "answer_text": row.answer_text, "source": row.source,
        "created_at": row.created_at, "updated_at": row.updated_at,
        "parent": submission_summary(row.parent_submission) if row.parent_submission else None,
        "children": [submission_summary(child) for child in sorted(row.child_submissions, key=lambda x: (x.attempt_number, x.id))],
        "exercise": {"id": exercise.id, "title": exercise.title, "prompt": exercise.prompt, "requirements": exercise.requirements},
        "lesson": {"id": lesson.id, "title": lesson.title, "position": lesson.position, "markdown_path": lesson.markdown_path},
        "course": {"id": course.id, "title": course.title, "plan_line_id": course.plan_line_id},
        "reviews": [{"id": review.id, "summary": review.summary, "detail_markdown": review.detail_markdown,
                     "rendered_html": render_markdown(review.detail_markdown), "issue_count": review.issue_count,
                     "decision": review.decision, "next_action": review.next_action, "created_at": review.created_at}
                    for review in sorted(row.reviews, key=lambda x: (x.created_at, x.id))],
    }
