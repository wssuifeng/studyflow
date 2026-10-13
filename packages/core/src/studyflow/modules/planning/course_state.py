"""Membership-scoped facts over immutable rounds, not global course status."""
import json
from sqlalchemy import select
from studyflow.modules.learning.models import CourseStudySession
from studyflow.modules.learning.study_sessions import outcome


def membership_state(db,course,item):
    rows=db.scalars(select(CourseStudySession).where(CourseStudySession.course_id==course.id).order_by(CourseStudySession.revision.desc())).all()
    study=next((r for r in rows if json.loads(r.snapshot_json)["course"].get("plan_line_id")==item.plan_line_id and r.abandoned_at is None),None)
    course.frozen_exercise_total=len([e for l in course.lessons for e in l.exercises])
    if study:
        state=outcome(db,study)
        from studyflow.modules.learning.english.models import EnglishStudyState
        english=db.get(EnglishStudyState,study.id) if course.learning_mode=="english" else None
        if english is not None:state["learning_submitted"]=english.completed
        course.study_status=state["study_status"];course.learning_submitted=state["learning_submitted"]
        course.study_session_id=study.id;course.waiting_count=state["waiting_count"];course.feedback_count=state["feedback_count"]
        course.exercise_completed=state["exercise_completed"];course.exercise_total=state["exercise_total"]
        course.progress_percent=round(course.exercise_completed/course.exercise_total*100) if course.exercise_total else 100 if state["learning_submitted"] else 0
    else:
        # Pre-freeze legacy facts only belong to the original course plan. Unknown attribution stays unknown.
        if course.plan_line_id!=item.plan_line_id or rows:
            course.learning_submitted=False;course.study_status="NOT_STARTED";course.study_session_id=None
            course.waiting_count=0;course.feedback_count=0;course.exercise_completed=0;course.progress_percent=0
    course.management_position=item.management_position;course.management_reason=item.management_reason;course.plan_course_item_id=item.id
    course.learning_group="OTHER" if item.management_position=="OTHER" else "COMPLETED" if course.learning_submitted else "PENDING"
