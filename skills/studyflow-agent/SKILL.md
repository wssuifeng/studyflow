---
name: studyflow-agent
description: Use the local StudyFlow CLI from any external Agent or script to discover the workspace, inspect current learning state, create or import courses, process review queues, and write lifecycle-safe feedback. Use when operating an explicit StudyFlow data workspace, including an installed desktop app-data workspace; do not use it for direct database access or unrelated project files.
metadata:
  version: "1.5.0"
---

# StudyFlow Agent

Use this skill when an external Agent needs to operate StudyFlow. The CLI is Agent-neutral: it is not restricted to Codex and must be usable by Claude, Trae, other Agents, or a human script.

## Non-negotiable boundaries

- Treat the selected StudyFlow data workspace as the content boundary. The approved CLI installation/source checkout may be outside it; do not recursively search unrelated directories to find an executable.
- Do not connect to the database directly, write SQL, edit SQLite/MySQL files, or bypass the CLI service layer.
- Do not copy a live SQLite file for migration or backup; use the workspace export/import commands so the database snapshot and Markdown manifest are validated together.
- Do not store database passwords in Markdown, prompts, source files, command history, or skill files. `doctor` output is safe to report but credentials are not.
- Never overwrite original Markdown, original answers, or prior review records. Corrections and retests are new records linked to their parent.
- A generated document, submitted answer, or passing-looking text is not proof that the learner mastered the material. Preserve the lifecycle status returned by the CLI.
- Do not claim a command succeeded unless its process exit code is zero and the JSON parses successfully.

## Minimal discovery sequence

1. Resolve the data workspace from the user's explicit path or the desktop's confirmed workspace. The installation directory is not the data workspace. An installed desktop normally uses `$env:APPDATA\local.studyflow.desktop`; a source checkout and a smoke workspace are separate roots. Set `STUDYFLOW_WORKSPACE` only in this process and verify the absolute `workspace.root` returned by the CLI before any write. Do not use `setx` or silently switch roots.
2. Prefer an available `studyflow` CLI. MSI 1.3.0 includes desktop/Engine, not a standalone CLI, and does not add PATH. For a known source checkout:

   ```powershell
   $env:STUDYFLOW_WORKSPACE = '<explicit-data-workspace>'
   & '<source-checkout>\studyflow_app\.venv\Scripts\python.exe' -X utf8 -m studyflow <command>
   ```

3. Run `version`, `capabilities`, `doctor` and `today` with `--format json`. Verify zero exit status, valid JSON, `ok=true`, and the intended workspace. Discover commands rather than assuming version support.
4. If `doctor.healthy` is false, stop writes and follow its `next_action`. `workspace.governance_ready=false` alone is not a failure: app-data can be healthy without project docs/control files. Never initialize/reset an existing workspace or copy a governance skeleton there to change that flag.
5. Read project governance only if present and relevant. In an app-data workspace, use `today`, plan/course details, queue context and relevant documents via CLI. Do not ingest all content.

The stable response envelope is in [CLI contract](references/cli-contract.md). Vue has a separate Engine protocol; `course.answers.submit` and other Engine method names are not shell commands. External Agents use only CLI commands advertised by `capabilities`.

## Common workflows

### Inspect current work

- Use `studyflow today --format json` for the current date and `--date YYYY-MM-DD` for another date.
- Use `studyflow status --format json` only as a backwards-compatible alias of `today`.
- Use `studyflow assignment queue --format json` to see `waiting_review`, `needs_revision`, and `waiting_retest`. Each item is a current leaf of an answer version chain; a parent with a correction/retest child is intentionally excluded.
- Queue items include the exercise/course/knowledge-point context, Markdown reference path, plan, answer text, parent/attempt metadata, source, and `next_action`; use these as routing context, then read `submission get` before writing feedback.
- Select only the queue item needed for the current task; do not batch-review unrelated submissions without an explicit request.



### Workspace backup and migration

Use the CLI for portable workspace migration; never copy `.studyflow/studyflow.db` while the app or Engine may be writing it:

```text
studyflow workspace export --output <backup.zip> --format json
`$env:STUDYFLOW_WORKSPACE = '<new-workspace-directory>'`
studyflow workspace import --file <backup.zip> --target $env:STUDYFLOW_WORKSPACE --format json
studyflow doctor --format json
studyflow today --format json
```

Rules:

- Export produces a ZIP containing `manifest.json`, a SQLite consistency snapshot, and declared Markdown files. The manifest records the workspace format, schema revision, file sizes and SHA-256 values.
- Import must target a new directory or an explicitly selected replacement directory. It validates archive paths, declared members, schema revision, database hash and Markdown hashes before switching; an existing target is renamed aside rather than deleted.
- After import, run `doctor` and a read-only command such as `today` before any write operation. If import fails, preserve the original workspace and report the CLI error/next action.
- The current format is for the managed SQLite/Markdown local workspace. Do not represent it as a formal MySQL production backup, and never put database credentials in archive metadata or commands.

### Create or import course material

- Create the plan line first if it does not exist: `studyflow plan list --format json`, then `studyflow plan create --name "..." --format json`.
- Prefer Markdown with Front Matter. For `course import --file`, relative paths resolve against the CLI process working directory before service validation; when running from another checkout, pass the absolute file path inside the selected data workspace. `document read --path` instead takes a workspace-relative path.
- Before import, verify the file is inside the workspace and contains the required `course`, `lesson`, and `plan_line` metadata.
- For multiple ordered knowledge points, import lesson files in the desired sequence with the same `course`/`plan_line` and distinct `lesson` titles. Do not create a separate course per knowledge point.
- Include `exercises` in Front Matter when practice is requested. Reading-only courses are valid when wanted; otherwise they are not practice-ready. After import, verify lesson order, `knowledge_total`, `exercise_total`, plan linkage and requested scheduling through CLI details.
- Importing an already registered path does not append newly added exercises. Do not claim such an update succeeded or edit the database to fill the gap; use available capabilities and report unsupported editing.
- Creating a course does not authorize learner answers. Simulated submissions require explicit authorization, a named isolated/demo workspace or course, and a report that they are product-test data, not learning evidence.

### Whole-course answer sheet

The UI saves/submits a course together; reviews and immutable history remain per exercise. Read `course answers get` first. Use [whole-course contract](references/course-answers.md) for exact fields, optimistic versions, stable idempotency keys and rollback. Do not loop individual submission commands to imitate an atomic course operation.

### Review, correction, and retest lifecycle

1. Read the queue item, then run `studyflow submission get --id <id> --format json` to read the original answer, exercise constraints, review history, and parent/child versions. Use `studyflow course detail --id <id> --format json` for the ordered knowledge points and reading progress. Read Markdown through `studyflow document read --path <relative-path> --format json`.
2. Produce a review that preserves the learner's original wording, identifies the exact error or missing constraint, explains why, gives the corrected form, and states the next action.
3. Write the review with a stable idempotency key when retrying is possible. Reusing that key is safe only when submission, decision, summary, detail, issue count, and next action are identical; a changed payload returns `IDEMPOTENCY_KEY_CONFLICT`:

   ```text
   studyflow review write --submission <id> --summary <summary> --file <review.md> --decision REVISION_REQUIRED --next-action "提交修正版" --idempotency-key <stable-key> --format json
   ```

4. For `REVISION_REQUIRED`, the learner normally writes a correction in the UI. Only with explicit authorization to submit on their behalf, the Agent can create a new submission:

   ```text
   studyflow submission revise --parent <submission-id> --file <answer.md> --format json
   ```

5. For `RETEST_REQUIRED`, the learner normally completes the UI retest. Only with explicit authorization, the Agent can create a new submission:

   ```text
   studyflow submission retest --parent <submission-id> --file <answer.md> --format json
   ```

6. A review can only be written for an item currently returned as `WAITING_REVIEW`; after a write, re-reading the queue is mandatory.
7. Do not call `review write` on a parent again merely to change wording. Use the lifecycle returned by the CLI and write a new follow-up only when the domain permits it.
8. Follow-up CLI operations are recorded with source `AGENT_CLI`; the returned child enters `WAITING_REVIEW`, and the parent remains immutable.
9. Re-read `assignment queue` after every write and report the next action. A course can mix passed, waiting and follow-up questions; one passed question is not the course passing or proof of mastery.

### Governance synchronization

When the user asks to persist a meaningful StudyFlow change, update the relevant Markdown control documents only after the CLI operation succeeds. Keep the root index, current board, and context snapshot consistent; do not invent completion evidence. Use `studyflow snapshot generate --scope today --format json` for a structured snapshot, then manually synchronize governance documents when the change affects project state.

## Failure recovery

- Parse stderr as JSON when present. Stable errors include `ok: false`, `error_code`, `message`, and `next_action`.
- For `INVALID_STATE_TRANSITION`, inspect the parent submission and queue again; do not force a status by editing the database.
- For path or import errors, correct the file boundary or Front Matter and retry with a new idempotency key only if the first command did not succeed.
- For a timeout or disconnected process, first re-run the same read-only discovery command. For writes, use the same idempotency key before attempting a new write.
- If the CLI returns an internal error or the database is unavailable, stop and report the exact next action instead of modifying unrelated files.

## Reporting

Every completed operation report should include:

- command and exit status;
- IDs or paths returned by StudyFlow;
- lifecycle decision and next action;
- files changed, if any;
- validation command and result.

Read the supporting contract only when exact fields, exit behavior, or a command example is needed.
