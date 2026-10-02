# Whole-course answers · app 1.3.0 / protocol 1.2

Use after capability discovery and authorization for answer submission or isolated product testing. Creating courses is not permission to invent learner answers.

## Read first

```text
studyflow course detail --id <course-id> --format json
studyflow course answers get --id <course-id> --format json
```

Course detail supplies ordered lessons/exercise IDs. Answers get returns `course_id`, `answers`, `next_action`. Each answer has `exercise_id`, `action`, `draft` and `submission` (details or null).

- `FIRST`: no formal answer; writable.
- `REVISION`: latest formal state `NEEDS_REVISION`; new correction links to that parent.
- `RETEST`: latest formal state `RETEST_REQUIRED`; new retest links to that parent.
- `LOCKED`: passed or awaiting review; exclude from new writes.

## UTF-8 JSON file inside the selected workspace

```json
{
  "answers": [
    {"exercise_id": "<first-exercise>", "answer_text": "<authorized answer>"},
    {"exercise_id": "<follow-up-exercise>", "answer_text": "<authorized correction>", "parent_submission_id": "<latest-formal-id>"}
  ]
}
```

To update a saved draft, also send its current `submission_id` and positive `expected_version`, keeping `parent_submission_id` for follow-ups. Omit unused ID fields, not null/empty placeholders. Use IDs/versions just read.

```text
studyflow course answers save --id <course-id> --file <answers.json> --idempotency-key <save-key> --format json
studyflow course answers submit --id <course-id> --file <answers.json> --idempotency-key <submit-key> --format json
```

- Save can retain empty drafts. Submit requires all currently writable questions, nonblank. Exclude locked/passed questions.
- One command is one transaction. Invalid/cross-course/duplicate IDs, missing answers or stale versions cause whole-batch rollback. Do not fall back to individual writes to bypass failure.
- Read back after saving, before submit; use returned draft IDs/versions. Save and submit are separate operations with different keys.
- Identical normalized payload+key returns the original response snapshot. Changed content yields `IDEMPOTENCY_KEY_CONFLICT`. Retry a lost response with the original payload/key. Changed answers need a new key after state refresh.
- On `VERSION_CONFLICT`, refresh/reconcile, not force database versions. On `INCOMPLETE_COURSE_ANSWERS`, complete the writable set/nonblank answers.
- Successful submit returns `WAITING_REVIEW`. Follow-ups preserve parents and use `REVISION`/`RETEST`. CLI source is `AGENT_CLI`, not learner UI `USER_WEB`.

Re-read `course answers get` and `assignment queue`; report exact IDs, question states and next action. Reviews still use `review write` per queued leaf. A product-test lifecycle is not evidence of learner mastery.


## Fixed local study context

When `course_study_get` is advertised, use the queued `study_session_id` with `course study-detail --study-id <id> --format json` for the frozen question set. `course detail` remains the live source and may include changed/new questions not in the current round. Pass `study_session_id` in authorized answer JSON. Do not substitute live material for `submission get.study_context`; missing historical context is explicitly `LEGACY_UNVERSIONED`. The learner uses knowledge and questions in one UI, can skip while saving drafts, and formally submits at course end; no per-knowledge-point formal submission is required.
