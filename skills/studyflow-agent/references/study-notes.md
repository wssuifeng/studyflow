# Personal learning notes (app 1.4.0 additive capability)

Default in 1.5.0 is the continuous [plan notebook](plan-notebooks.md). This old API is kept for preservation and explicit compatibility; do not migrate automatically.

Read this only for an explicitly requested per-knowledge-point scratch-note operation. It is not the answer-sheet contract.

## Discover and read

A study note is identified by `study_session_id + lesson_id`; the lesson must belong to that frozen round. Use IDs already returned by supported CLI reads. Do not open a new learning round merely to obtain a note ID.

```text
studyflow course notes-get --study-id <study-session-id> --format json
```

The JSON contains `ok`, `study_session_id` and `notes`. Each note contains `id`, `lesson_id`, `text`, `version` and `updated_at`. No row means initial version 0, not an error.

## Authorized write

A UTF-8 (BOM accepted) .txt, .md or .markdown file must be inside the selected data workspace. Relative note paths resolve against that workspace, unlike course-import process-cwd resolution. Markdown is saved as plain note text and does not need Front Matter. Maximum text is 200,000 characters; an empty file intentionally clears the note.

```text
studyflow course notes-save --study-id <study-session-id> --lesson-id <lesson-id> --file <workspace-relative-note.txt> --expected-version <0-or-read-version> --idempotency-key <stable-key> --format json
```

The response contains `ok`, `study_session_id` and `note`; use its new version for a later edit. Read back with notes-get. Note events have source `AGENT_CLI`, and notes never enter assignment queue or replace any answer.

## Conflict and recovery

- Same key + same full payload replays the original response; different payload under that key is `IDEMPOTENCY_KEY_CONFLICT`.
- A stale version is `VERSION_CONFLICT`. Preserve both the read workspace text and proposed edit; do not silently overwrite another window. Obtain the user's choice before a new write.
- For uncertain I/O, retain original text, expected version and key. After recovery, retry that unchanged request before starting a different edit.
- Out-of-workspace paths, unsupported extensions, missing files and non-UTF-8 content are rejected without creating a note or review task.

Do not use this operation to simulate a learner's understanding or automatically turn personal scratch text into submitted answers.
