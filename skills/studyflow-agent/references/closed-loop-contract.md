# Closed-loop CLI contract · app/Core 1.7.0, repository Skill 2.1.0

## Discovery and transport

Use the installed `binaries/studyflow.exe` absolute path, arbitrary cwd, explicit `STUDYFLOW_WORKSPACE`. `version`, `capabilities`, `doctor --format json` must confirm the intended workspace before writes. `call --method system.schema --format json` returns versioned schemas for supported requests. All methods are discovered in `capabilities.engine_capabilities`; JSON request files preserve UTF-8 text and avoid shell quoting. Command exits nonzero on `ok=false`. Never use SQL to author content or answer on behalf of the learner.

```powershell
& '<install>/binaries/studyflow.exe' call --method assignment.summary --file '<request.json>' --format json
```

## Queue and batch context

`assignment.summary`: role=agent/learner/all, optional plan_line_id/course_id/status/cursor, limit=1..100, history=true for passed history. Agent actions: REVIEW, PUBLISH_RETEST. Learner actions: REVISE, RETEST. A summary contains IDs/status/version/next action, no answer or teaching body. `assignment.context` accepts submission_ids (1..100); its items reference contexts by ID, so each frozen knowledge-point material appears once. The old assignment queue (--full) remains opt-in for compatibility; do not read it for routine navigation.

## Structured review

`review.write` accepts existing fields plus `issues`: array of objects with **quote, location, reason, guidance, next_action**. Quote must be an actual substring of the target original answer. Do not invent an error or a quotation. Review PASSED with issues is refused. Original answer, frozen question, correction and new retest remain separate evidence. A stale or already reviewed answer cannot be reviewed again with a new key.

## Actual retest

After RETEST_REQUIRED, publish `review.retest.publish`: parent_submission_id, title, prompt, objective, idempotency_key, optional requirements and agent_reference. Questions are frozen at publication; a second changed question is refused. agent_reference is private to Agent context and never returned by course/learner APIs. The learner answers through the course editor with retest_task_id. Before publication, the learner sees WAITING_RETEST_TASK; it is not permission for an Agent to fabricate a learner answer. Unversioned legacy retest history remains readable.

## Safe course revision

`course.update.preview`: course_id, path (package JSON), expected_revision. Inspect added/removed/changed questions, order, affected rounds and preview_hash. Then `course.update.apply`: same inputs plus preview_hash and idempotency_key. Source changes after preview are refused. Course and plan sequence identities remain the same; original entities, answers, notebook sources and active frozen rounds remain. A semantic replacement should use a new ID, not silently repurpose the same ID as a different question.

## Plans, notes and workspace

`plan.edit`: plan_line_id, expected_version, idempotency_key, operation, values. UPDATE edits name/priority/status/focus_course_id; REORDER requires all course_ids; SCHEDULE needs course_id/date and optional start_time/end_time; RESCHEDULE and CANCEL_SCHEDULE reference schedule_id. Dates do not mark learning completed. `plan.schedule.list` reads arrangements.

`plan.notebook.search`: plan_line_id, query and optional course_id/lesson_id. `plan.notebook.export` returns UTF-8 Markdown; `course.source.read` returns read-only frozen study_session_id/lesson_id/optional block_id, never opens a new round.

`workspace.export`, `workspace.validate`, `workspace.restore` accept a backup path; restore also target_root. Restoration into a running workspace is refused by a cross-process lease. Default to a new directory; original directory is preserved. The desktop confirms switching only after tool-window save coordination. Do not treat SQLite online backup as a license to rename an active database.

## Uncertain outcomes

ENGINE_TIMEOUT/ENGINE_UNCONFIRMED/CONNECTION_FAILED means a write may have committed. Preserve the original payload/key and inputs. Read back or retry the exact same payload; never generate a fresh key to retry an uncertain write. ENGINE_BUSY explicitly means that request was not dispatched. IDEMPOTENCY_KEY_CONFLICT is a changed request; IDEMPOTENCY_UNVERIFIABLE is legacy history without a verifiable payload hash and requires readback, not false success. Historical branching returns SUBMISSION_BRANCH_CONFLICT. Resolve only with explicit authorization using submission.resolve-branch, parent_submission_id, child_submission_id and audit reason; no record is deleted.

## English and errors

For current-source English capabilities read [English operations](english-operations.md), including exercise extensions, frozen training, original-item retests and plan/domain-scoped mistakes. Installed app1.7.0 artifacts built before this work do not acquire English support by updating a Skill file. Discover the executable's capabilities. New-sentence English migration retests, TTS registration and English detached answer editors remain unsupported; do not apply the ordinary retest editor instructions to an English task by assumption.


## Explicit safe restart of a general round

Not a publishing workflow and not course deletion. Only with learner authorization:

1. `course.study.restart.preview` with study_session_id. Read can_restart, blocked_reasons, expected_version and expected_content_hash. It does not acquire a writer lease or close the round.
2. The desktop coordinates all editors; do not use CLI to bypass unsaved/uncertain input in open windows. A CLI actor cannot inspect unsubmitted editor memory, so request desktop confirmation rather than inferring safety from low reading percent.
3. `course.study.restart` uses exactly study_session_id, expected_version, expected_content_hash and a stable idempotency_key. Any draft (including empty), answer-write receipt, submission or English training record blocks restart. A changed version/source rejects without ending the old round.
4. Success returns the new frozen round; the old has study_status ABANDONED, is_current=false, retained notes and immutable history. It does not mean passed or mastered. Late old writes are rejected.
5. Uncertain response: preserve/retry original payload and key. Do not create another round with a new key. No automatic restart/cleanup to make new course formatting visible.
