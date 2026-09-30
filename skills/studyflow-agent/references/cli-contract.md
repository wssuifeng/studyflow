# StudyFlow Agent CLI Contract · Skill v1.5 (app 1.3.0 / protocol 1.2)

## CLI versus desktop Engine boundary

The desktop Vue frontend uses a separate JSON-RPC protocol over the Python Engine. It includes `plan.detail`, `course.detail`, `document.read`, `submission.get`, `submission.draft.save`, `submission.submit`, and `learning.progress.save`. These are Engine method names, not shell commands. `studyflow plan detail --id <id>`, `studyflow course detail --id <id>`, `studyflow submission get --id <id>` and `studyflow document read --path <relative-path>` are real read-only CLI commands sharing the Engine service data. All support `--format json`. External Agents must call only capabilities advertised by `studyflow capabilities`; do not run these method names as CLI commands or claim that they are available through the CLI.

## Invocation

The preferred interface is an installed `studyflow` executable. For this repository's development checkout, invoke:

```powershell
.\studyflow_app\.venv\Scripts\python.exe -m studyflow <command>
```

Use `--format json` for advertised automation commands. `init` has text-only output; do not append an unsupported flag or run init on healthy existing data. Verify initialization with JSON doctor. Human-readable text is not a machine contract.

## Read-only discovery envelope

`version`, `capabilities`, `doctor`, and `today` return JSON objects with:

```json
{
  "ok": true,
  "protocol_version": "1.2",
  "workspace": {
    "root": "...",
    "exists": true
  },
  "database": {
    "url": "sqlite:///...",
    "driver": "sqlite",
    "managed_by_app": true,
    "status": "not_checked | ready | not_initialized | incomplete | unavailable",
    "reachable": true
  },
  "capabilities": [],
  "next_action": "..."
}
```

`doctor` additionally reports `workspace.governance_files`, `workspace.governance_ready`, `database.required_tables`, `database.path` for SQLite, and `healthy`. Database URLs are rendered with passwords hidden. `healthy=true` is authoritative operational readiness; `governance_ready=false` is normal for app-data and does not authorize adding project docs.

`version` additionally reports `app_version` and `python_version`.

`capabilities` reports a list of capability objects:

```json
{"name": "assignment_queue", "command": "studyflow assignment queue --format json", "kind": "read"}
```

`today` additionally reports `date`, `primary_task`, `current_course`, `courses`, `tasks`, and `queue_counts`.

## Queue contract

```text
studyflow assignment queue --format json
```

Returns `waiting_review`, `needs_revision`, `waiting_retest`, and `items`. Each item includes at least:

- `id`
- `kind`, `label`, `status`
- `exercise_id`, `exercise_title`
- `course_id`, `course_title`
- `lesson_id`, `lesson_title`, `markdown_path`
- `plan_line_id`, `plan_line`
- `parent_submission_id`, `attempt_number`, `attempt_kind`
- `source`, `answer_text`, `review_count`, `context`
- `next_action`

Queue contains only leaf submissions. When a correction or retest child exists, the parent is not returned again.

## Review contract

```text
studyflow review write \
  --submission <id> \
  --summary <short-summary> \
  --file <review-markdown> \
  --decision PASSED|REVISION_REQUIRED|RETEST_REQUIRED \
  --next-action <next-step> \
  --idempotency-key <stable-key> \
  --format json
```

Successful output contains `review_id`, `submission_id`, `decision`, `next_action`, and `needs_revision`. A review is accepted only for a currently `WAITING_REVIEW` submission. Reusing an idempotency key with changed content returns `IDEMPOTENCY_KEY_CONFLICT`.

## Follow-up submission contract

```text
studyflow submission revise --parent <id> --file <answer.md> --format json
studyflow submission retest --parent <id> --file <answer.md> --format json
```

The output contains a new `submission_id`, its `parent_submission_id`, `attempt_number`, `attempt_kind`, `status`, `source`, and `next_action`. CLI-created follow-ups use source `AGENT_CLI`; parent records remain immutable. Reusing an idempotency key with a different parent, attempt type, or answer returns `IDEMPOTENCY_KEY_CONFLICT`.

## Course import contract

```text
studyflow plan list --format json
studyflow plan create --name "计划名称" --format json
studyflow course import --file <lesson.md> --format json
```

Course Markdown requires `course`, `lesson`, and `plan_line` Front Matter. The source file is not rewritten by import. Import `--file` is a filesystem path relative to the CLI process working directory; pass an absolute workspace-contained path if the process runs from a separate source checkout. Do not confuse it with `document read --path`, which is workspace-relative.


## Workspace export/import contract (S4)

```text
studyflow workspace export --output <backup.zip> --format json
`$env:STUDYFLOW_WORKSPACE = '<new-workspace-directory>'`
studyflow workspace import --file <backup.zip> --target $env:STUDYFLOW_WORKSPACE --format json
```

`workspace export` returns a JSON result containing the archive path, workspace root, schema revision, database metadata and declared Markdown file count. The archive contains only `manifest.json`, `database/studyflow.db`, and declared Markdown members.

`workspace import` validates the manifest format, schema revision, safe relative paths, archive member set, database size/SHA-256 and Markdown size/SHA-256 before atomically switching the target. If the target already exists, the prior directory is retained under a generated backup name; failed validation must not replace the original target.

Agents must:

1. never copy or edit `.studyflow/studyflow.db` directly;
2. import into a new or explicitly selected workspace directory;
3. set `STUDYFLOW_WORKSPACE` to the imported target, then run `doctor --format json`;
4. run a read-only command such as `today` before writing new state;
5. never place database passwords in commands, manifests or reports.

This contract currently covers the managed SQLite/Markdown desktop workspace, not formal MySQL production backup/restore.

## Exit and error behavior

- Exit code `0` means the command completed and stdout must parse as JSON when `--format json` is used.
- Exit code `1` means the operation failed. Stderr contains a JSON object with `ok: false`, `error_code`, `message`, and `next_action`.
- Never treat a non-empty stdout or a human-readable message as success.
- Never expose, copy, or log database passwords.

## Shared detail commands (S1)

```text
studyflow plan detail --id <plan-id> --format json
studyflow course detail --id <course-id> --format json
studyflow submission get --id <submission-id> --format json
studyflow document read --path <workspace-relative.md> --format json
```

Course detail returns ordered `lessons`, separate reading `progress` and exercise `latest_submission` / `draft`. Submission get returns a `submission` object with the original answer, context, parent/children, reviews and next action. Neither read command mutates an answer or infers mastery. Document read rejects absolute paths, parent traversal, out-of-workspace real paths and non-Markdown files.


## Whole-course answers (app 1.3.0)

CLI `course answers get/save/submit` correspond to Engine `course.answers.get`, `course.answers.draft.save`, `course.answers.submit`; they are different syntaxes. See [batch contract](course-answers.md) for payload and retry rules. UI writes are course-level; review queues/history remain per exercise.
