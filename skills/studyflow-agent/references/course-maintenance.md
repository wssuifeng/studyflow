# Course replacement and current-learning reset

Use for explicitly authorized course maintenance, not learner simulation or grading. Discover actual installed capabilities first; do not infer availability from repository version.

## 1. Replace content, keep course identity

1. Read `course detail --id <id>` and source only within the authorized scope. Prepare a valid whole-course package in the same plan and mode; stable lesson/exercise identities represent the same semantic objects, not arbitrary reused IDs.
2. `course update-preview --id <id> --file <absolute-package.json> --expected-revision <n> --format json`.
3. Inspect removals, additions and changes, then `course update-apply --id <id> --file <absolute-package.json> --expected-revision <n> --preview-hash <hash> --idempotency-key <stable-key> --format json`.
4. A material change resets this course's current learning in the same transaction, including rounds with drafts or submitted/waiting-review answers. Notes and history remain. Failed/no-op updates do not reset; retry the exact original request/key when the result is uncertain.
5. `course readback-check --course <id> --format json`. `no_active_round` means next open reads latest; it does not mean passed. Normal update and reset do not require deleting/reimporting the course.

Existing `call --method course.update.preview/apply --file <request.json>` remains supported.

## 2. Repair an already-published course stuck on old material

Do not fabricate another content change or replay an old publication to trigger reset.

- Preview: `course reset-learning --id <id> --dry-run --format json` (read-only, no lease or write).
- Execute: `course reset-learning --id <id> --confirm --state-hash <state_hash> --content-hash <content_hash> --idempotency-key <stable-key> --format json`.
- Engine equivalents: `course.learning.reset.preview` with course_id; `.apply` with course_id, expected_state_hash, expected_content_hash, idempotency_key and confirm=true.
- This explicitly resets current reading, answers, training and completion, opens latest material from the start, and removes sealed rounds from actionable assignment queues. It retains historical answers, errors and notes; those are not carried into the new learning as success.
- Concurrent state/content changes require a fresh preview and renewed confirmation, not silently replacing the expected hashes. Unknown write outcome requires original-payload retry, never a new key. Late old-window saves are rejected; preserve/export unsaved local editor input before confirming.
- Agent must have user authorization for course and reset purpose; prior read access or new content alone is not blanket authorization to reset unrelated courses. No synthetic submissions or automatic grading.

## 3. Destructive fallback, separate from ordinary reset

Only if explicitly chosen and valid packages are ready: preview `workspace purge-courses --id <id> --dry-run --format json`, export/validate a consistency backup, then `workspace purge-courses --id <id> --confirm --backup <backup.zip> --format json`. Repeat --id for an explicitly authorized set. Omitting --id targets all courses and is not a default fallback. Deletion removes course-owned answers/reviews/training/error records and changes identity on reimport; read inventory/dependencies and preserve personal notes. Do not directly edit SQL or delete workspace files.

The legacy course.study.restart (study_session_id, not course_id) is not this maintenance path. In the modern desktop opt-in, restart.preview includes reset_current_state=true and returns expected_state_hash; restart confirmation carries both that flag and hash. Without the flag the historical evidence-free behavior remains for older callers.
