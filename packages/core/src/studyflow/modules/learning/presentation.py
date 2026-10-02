from studyflow.infrastructure.markdown import render_markdown


def submission_summary(row):
    return {"id": row.id, "exercise_id": row.exercise_id, "task_id": row.task_id,
            "parent_submission_id": row.parent_submission_id, "status": row.status,
            "version": row.version, "attempt_number": row.attempt_number,
            "attempt_kind": row.attempt_kind, "next_action": row.next_action,
            "study_session_id": row.study_session_id, "batch_id": row.batch_id}

def submission_detail(row):
    exercise = row.exercise
    lesson = exercise.lesson
    course = lesson.course
    from .study_sessions import frozen_context
    context = frozen_context(row)
    return {
        **submission_summary(row), "study_context": context, "snapshot_status": "FROZEN" if context else "LEGACY_UNVERSIONED", "answer_text": row.answer_text, "source": row.source,
        "created_at": row.created_at, "updated_at": row.updated_at,
        "parent": submission_summary(row.parent_submission) if row.parent_submission else None,
        "children": [submission_summary(child) for child in sorted(row.child_submissions, key=lambda x: (x.attempt_number, x.id))],
        "exercise": context["exercise"] if context else {"id": exercise.id, "title": exercise.title, "prompt": exercise.prompt, "requirements": exercise.requirements},
        "lesson": context["lesson"] if context else {"id": lesson.id, "title": lesson.title, "position": lesson.position, "markdown_path": lesson.markdown_path},
        "course": context["course"] if context else {"id": course.id, "title": course.title, "plan_line_id": course.plan_line_id},
        "reviews": [{"id": review.id, "summary": review.summary, "detail_markdown": review.detail_markdown,
                     "rendered_html": render_markdown(review.detail_markdown), "issue_count": review.issue_count,
                     "decision": review.decision, "next_action": review.next_action, "created_at": review.created_at}
                    for review in sorted(row.reviews, key=lambda x: (x.created_at, x.id))],
    }
