# Closed-loop CLI contract · app/Core 1.7.0, Skill 2.0.0

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
