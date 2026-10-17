"""W2 material reset: a successful content update seals active rounds; the next open starts fresh on latest material."""
import json
import pytest
from sqlalchemy import select
from studyflow.shared.domain import DomainError
from studyflow.modules.courses.revisions import preview, apply
from studyflow.modules.learning.models import CourseStudySession
from test_course_packages import sample, package_file
from test_english_specialty import english_package, install as install_english, finish
from test_q234_delivery import upgraded


def install(app_service, tmp_path):
    app_service.create_plan_line('Testing')
    result = app_service.import_course_package(package_file(tmp_path, upgraded()))
    opened = app_service.open_course_study(result['course_id'], 'reset-open', plan_line_id=result['plan_id'])
    return result, opened


def revise(app_service, tmp_path, course_id, revision, key, mutate=None):
    data = upgraded()
    if mutate:
        mutate(data)
    path = package_file(tmp_path, data)
    check = preview(app_service.courses, course_id, path, revision)
    return apply(app_service.courses, course_id, path, revision, check['preview_hash'], key)


def active_sessions(app_service, course_id):
    with app_service.session() as db:
        return db.scalars(select(CourseStudySession).where(CourseStudySession.course_id == course_id,
                                                           CourseStudySession.abandoned_at.is_(None))).all()


def test_content_update_resets_round_and_next_open_reads_latest(app_service, tmp_path):
    result, opened = install(app_service, tmp_path)
    course_id, sid = result['course_id'], opened['study']['id']
    lesson_id = opened['lessons'][0]['id']
    app_service.save_study_progress(sid, lesson_id, 60, 'half-way', expected_version=1)

    published = revise(app_service, tmp_path, course_id, 1, 'reset-once',
                        mutate=lambda d: d['lessons'][0]['exercises'][0].update(prompt='What does PC point to now?'))
    assert published['learning_state_reset'] is True
    with app_service.session() as db:
        assert db.get(CourseStudySession, sid).abandoned_at is not None

    reopened = app_service.open_course_study(course_id, 'reset-open-2', plan_line_id=result['plan_id'])
    assert reopened['study']['id'] != sid and reopened['study']['is_current'] is True
    assert reopened['study']['source_changed'] is False
    assert reopened['lessons'][0]['progress']['progress_percent'] == 0
    assert reopened['lessons'][0]['progress']['status'] == 'NOT_STARTED'
    assert reopened['lessons'][0]['exercises'][0]['prompt'] == 'What does PC point to now?'
    assert app_service.course_study_detail(sid)['study']['is_current'] is False


def test_reopen_with_stale_open_receipt_returns_new_round(app_service, tmp_path):
    """The reader persists its study-open key; replay after a reset must not resurrect the sealed round."""
    result, opened = install(app_service, tmp_path)
    course_id, sid = result['course_id'], opened['study']['id']
    revise(app_service, tmp_path, course_id, 1, 'reset-receipt',
           mutate=lambda d: d['lessons'][0]['exercises'][0].update(prompt='What does PC point to now?'))

    again = app_service.open_course_study(course_id, 'reset-open', plan_line_id=result['plan_id'])
    assert again['study']['id'] != sid and again['study']['is_current'] is True
    assert again['study']['source_changed'] is False
    assert again['lessons'][0]['exercises'][0]['prompt'] == 'What does PC point to now?'


def test_completed_english_round_resets_to_pending(app_service, tmp_path):
    course, opened = install_english(app_service, tmp_path)
    course_id, sid = course['course_id'], opened['study']['id']
    finish(app_service, opened)
    assert app_service.course_study_detail(sid)['course']['study_status'] == 'PASSED'
    assert app_service.plan_detail(course['plan_id'])['courses'][0]['learning_group'] == 'COMPLETED'

    data = english_package()
    data['lessons'][0]['exercises'][0]['english']['target'] = 'I enjoy tea.'
    path = tmp_path / 'revised.json'
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    proposal = preview(app_service.courses, course_id, path, 1)
    applied = apply(app_service.courses, course_id, path, 1, proposal['preview_hash'], 'reset-english')
    assert applied['learning_state_reset'] is True

    detail = app_service.plan_detail(course['plan_id'])['courses'][0]
    assert detail['learning_group'] == 'PENDING' and detail['study_status'] == 'NOT_STARTED'
    assert detail['exercise_completed'] == 0 and not detail['learning_submitted']

    fresh = app_service.open_course_study(course_id, 'reset-english-open')
    fresh_sid = fresh['study']['id']
    training = app_service.english.get(fresh_sid)
    assert training['position'] == 0 and training['completed'] is False
    assert all(row['answer_text'] == '' and not row['matched'] and row['error_count'] == 0 for row in training['items'])


def test_unchanged_update_does_not_reset(app_service, tmp_path):
    result, opened = install(app_service, tmp_path)
    course_id, sid = result['course_id'], opened['study']['id']
    published = revise(app_service, tmp_path, course_id, 1, 'noop-update')
    assert published['learning_state_reset'] is False
    assert active_sessions(app_service, course_id)
    same = app_service.open_course_study(course_id, 'reset-open-3', plan_line_id=result['plan_id'])
    assert same['study']['id'] == sid and same['study']['is_current'] is True


def test_failed_update_keeps_material_and_state(app_service, tmp_path):
    result, opened = install(app_service, tmp_path)
    course_id, sid = result['course_id'], opened['study']['id']
    data = upgraded()
    data['lessons'][0]['exercises'][0]['prompt'] = 'Never published'
    path = package_file(tmp_path, data)
    check = preview(app_service.courses, course_id, path, 1)
    with pytest.raises(DomainError) as failure:
        apply(app_service.courses, course_id, path, 1, '0' * 64, 'failed-update')
    assert failure.value.code == 'PREVIEW_CHANGED'
    assert app_service.course_study_detail(sid)['study']['is_current'] is True
    assert app_service.course_study_detail(sid)['lessons'][0]['exercises'][0]['prompt'] != 'Never published'
    assert active_sessions(app_service, course_id)


def test_apply_replay_does_not_reset_twice(app_service, tmp_path):
    result, opened = install(app_service, tmp_path)
    course_id = result['course_id']
    data = upgraded()
    data['lessons'][0]['blocks'][0]['sections'][0].update(body='Revised body.')
    path = package_file(tmp_path, data)
    check = preview(app_service.courses, course_id, path, 1)
    apply(app_service.courses, course_id, path, 1, check['preview_hash'], 'replay-key')
    first = app_service.open_course_study(course_id, 'after-replay')
    replayed = apply(app_service.courses, course_id, path, 1, check['preview_hash'], 'replay-key')
    assert replayed['ok'] is True
    second = app_service.open_course_study(course_id, 'after-replay-2')
    assert second['study']['id'] == first['study']['id']
    assert len(active_sessions(app_service, course_id)) == 1


def test_late_writes_are_rejected_without_polluting_new_round(app_service, tmp_path):
    result, opened = install(app_service, tmp_path)
    course_id, sid = result['course_id'], opened['study']['id']
    lesson_id = opened['lessons'][0]['id']
    revise(app_service, tmp_path, course_id, 1, 'reset-late',
           mutate=lambda d: d['lessons'][0]['blocks'][0]['sections'][0].update(body='New body for late checks.'))
    fresh = app_service.open_course_study(course_id, 'reset-fresh')
    fresh_sid = fresh['study']['id']

    with pytest.raises(DomainError) as progress_failure:
        app_service.save_study_progress(sid, lesson_id, 80, 'late', expected_version=1)
    assert progress_failure.value.code == 'STUDY_ROUND_SUPERSEDED'
    with pytest.raises(DomainError) as answer_failure:
        app_service.write_course_answers(course_id, [{'exercise_id': fresh['lessons'][0]['exercises'][0]['id'],
                                                      'answer_text': 'late draft'}], 'DRAFT_SAVE', 'late-draft',
                                         study_session_id=sid)
    assert answer_failure.value.code == 'STUDY_ROUND_SUPERSEDED'
    with app_service.session() as db:
        sealed = db.get(CourseStudySession, sid)
        assert sealed.abandoned_at is not None
        fresh_row = db.get(CourseStudySession, fresh_sid)
        assert json.loads(fresh_row.progress_json) == {}


def test_english_late_requests_rejected_after_reset(app_service, tmp_path):
    course, opened = install_english(app_service, tmp_path)
    course_id, sid = course['course_id'], opened['study']['id']
    item = app_service.english.get(sid)['items'][0]
    data = english_package()
    data['lessons'][0]['exercises'][0]['english']['target'] = 'I enjoy tea.'
    path = tmp_path / 'late.json'
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    proposal = preview(app_service.courses, course_id, path, 1)
    apply(app_service.courses, course_id, path, 1, proposal['preview_hash'], 'reset-english-late')

    with pytest.raises(DomainError) as late_save:
        app_service.english.save(sid, item['exercise_id'], 'I like tea', item['answer_version'], 'late-save')
    assert late_save.value.code == 'STUDY_ROUND_SUPERSEDED'
    with pytest.raises(DomainError) as late_check:
        app_service.english.check(sid, item['exercise_id'], item['answer_version'], 'late-check')
    assert late_check.value.code == 'STUDY_ROUND_SUPERSEDED'


def test_round_notes_stay_readable_and_plan_notes_untouched(app_service, tmp_path):
    result, opened = install(app_service, tmp_path)
    course_id, sid = result['course_id'], opened['study']['id']
    lesson_id = opened['lessons'][0]['id']
    app_service.save_study_note(sid, lesson_id, '本轮学习笔记', 0, 'note-before-reset')
    app_service.save_plan_notebook(result['plan_id'], [{'id': 'general', 'text': '计划笔记'}], 0, 'plan-note')

    revise(app_service, tmp_path, course_id, 1, 'reset-notes',
           mutate=lambda d: d['lessons'][0]['blocks'][0]['sections'][0].update(body='Notes reset body.'))
    assert any('本轮学习笔记' in row['text'] for row in app_service.study_notes(sid)['notes'])
    fresh = app_service.open_course_study(course_id, 'reset-notes-open', plan_line_id=result['plan_id'])
    app_service.save_study_note(fresh['study']['id'], fresh['lessons'][0]['id'], '新一轮笔记', 0, 'note-after-reset')
    assert any('新一轮笔记' in row['text'] for row in app_service.study_notes(fresh['study']['id'])['notes'])
    notebook = app_service.plan_notebook(result['plan_id'])
    assert '计划笔记' in json.dumps(notebook, ensure_ascii=False)


def test_old_window_sees_brief_superseded_state_not_old_material_banner(app_service, tmp_path):
    """After a reset the sealed round reports superseded + changed source, without requiring completion first."""
    result, opened = install(app_service, tmp_path)
    course_id, sid = result['course_id'], opened['study']['id']
    revise(app_service, tmp_path, course_id, 1, 'reset-window',
           mutate=lambda d: d['lessons'][0]['blocks'][0]['sections'][0].update(body='Window reset body.'))
    detail = app_service.course_study_detail(sid)['study']
    assert detail['is_current'] is False and detail['source_changed'] is True
