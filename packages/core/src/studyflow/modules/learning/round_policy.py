"""Next-round eligibility is not mastery; completed English training keeps old reviews."""
import json


SUBMITTED_STATES = frozenset({"WAITING_REVIEW", "PASSED", "RECHECKED", "REVIEWED"})


def next_round_allowed(db, study):
    from .study_sessions import exercise_ids, outcome, study_attempts
    if study.abandoned_at is not None:
        # A sealed round (course revision reset or explicit restart) is closed; nothing is in progress.
        return True
    if outcome(db, study)["study_status"] in {"PASSED", "READ_COMPLETED"}:
        return True
    frozen = json.loads(study.snapshot_json)
    if frozen["course"].get("learning_mode") != "english":
        return False
    from .english.models import EnglishStudyState
    training = db.get(EnglishStudyState, study.id)
    if not training or not training.completed:
        return False
    ids = exercise_ids(study)
    latest = study_attempts(db, study, include_drafts=True)
    return bool(ids) and all(eid in latest and latest[eid].status in SUBMITTED_STATES for eid in ids)


def round_start_info(db, study, live_revision):
    frozen_revision = json.loads(study.snapshot_json)["course"].get("content_revision") if study else None
    allowed = not study or next_round_allowed(db, study)
    english = bool(study and json.loads(study.snapshot_json)["course"].get("learning_mode") == "english")
    return {
        "can_start_new_round": allowed,
        "study_content_revision": frozen_revision,
        "source_changed": bool(study and frozen_revision is not None and frozen_revision != live_revision),
        "new_round_blocker": "" if allowed else "请先完成并提交本轮训练；需修正或复测的记录也要先处理。" if english else "完成当前作答与反馈后，再开始新版学习。",
    }
