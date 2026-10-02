from studyflow.infrastructure.markdown import render_markdown
from studyflow.modules.learning.presentation import submission_summary


def course_summary(row):
    schedule = getattr(row, "schedule_item", None)
    return {"id": row.id, "title": row.title, "summary": row.summary,
            "subject": row.subject, "content_type": row.content_type,
            "difficulty": row.difficulty, "source_type": row.source_type,
            "study_status":getattr(row,"study_status","NOT_STARTED"),
            "learning_submitted":getattr(row,"learning_submitted",False),
            "study_session_id":getattr(row,"study_session_id",None),
            "waiting_count":getattr(row,"waiting_count",0),"feedback_count":getattr(row,"feedback_count",0),
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
