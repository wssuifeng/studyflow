---
name: studyflow-agent
description: Use the local StudyFlow CLI from any external Agent or script to discover the workspace, inspect current learning state, create or import courses, process review queues, and write lifecycle-safe feedback. Use when operating an explicit StudyFlow data workspace, including an installed desktop app-data workspace; do not use it for direct database access or unrelated project files.
metadata:
  version: "2.0.0"
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
2. Prefer the approved installation's CLI path shown in Workspace settings or `system.installation.cli_path`. App 1.7.0 packages `binaries/studyflow.exe`; call it by absolute path with the explicit workspace. Older 1.5/1.6 installers have no independent CLI. Do not assume `studyflow` is on PATH or guess between multiple installations. Only for a known source checkout / older installer use:

   ```powershell
   $env:STUDYFLOW_WORKSPACE = '<explicit-data-workspace>'
   & '<source-checkout>\packages\core\.venv\Scripts\python.exe' -X utf8 -m studyflow <command>
   ```

   Windows source launchers can retain a `Low Mandatory Level` label from an older sandbox even after the current task is authorized for ordinary local access. For that diagnosed case only, see [Windows CLI runtime diagnosis](references/windows-cli-runtime.md); do not use it to escape an active sandbox.

3. Run `version`, `capabilities`, `doctor` and `today` with `--format json`. Verify zero exit status, valid JSON, `ok=true`, and the intended workspace. Discover commands rather than assuming version support.
4. Before writes, require both `doctor.healthy=true` and `workspace.writable=true`. Older app1.3.0 can report `healthy=true` for a reachable but read-only database; app1.4.0 includes actual write/flush/fsync probes. Require both flags for compatibility; reachability is never write authorization. If either flag is false, stop writes and follow the diagnostic next action. Do not change ACLs, clear file protection, bypass the Agent sandbox, or silently switch data workspaces. `workspace.governance_ready=false` alone is not a failure: app-data can be healthy without project docs/control files. Never initialize/reset an existing workspace or copy a governance skeleton there to change that flag.
5. Read project governance only if present and relevant. In an app-data workspace, use `today`, plan/course details, queue context and relevant documents via CLI. Do not ingest all content.

The stable response envelope is in [CLI contract](references/cli-contract.md). App 1.7.0 includes an installed `binaries/studyflow.exe` from the same frozen Core as Engine. No source tree, Python, venv or system PATH is required. Invoke its absolute path and set `STUDYFLOW_WORKSPACE` explicitly. Engine method names are not shell commands: the neutral CLI exposes `call --method <method> --file <request.json> --format json`. Discover `engine_capabilities` before using it; old named commands remain compatible. Read [closed-loop contract](references/closed-loop-contract.md) for compact queues, structured reviews, retests and course updates.

## Common workflows

### Inspect current work

- Use `studyflow today --format json` for the current date and `--date YYYY-MM-DD` for another date.
- Use `studyflow status --format json` only as a backwards-compatible alias of `today`.
- Prefer `call --method assignment.summary --file <queue.json> --format json` (`role=agent`, `limit<=100`). The summary contains no answers/body. Fetch only selected IDs with `assignment.context`; shared frozen materials are returned once in `contexts`. Legacy `studyflow assignment queue --full --format json` remains available to see `waiting_review`, `needs_revision`, and `waiting_retest`. Each item is a current leaf of an answer version chain; a parent with a correction/retest child is intentionally excluded.
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

### Structured teaching components (preferred for new authored courses)

For a new multi-knowledge-point course, discover package commands and read [course packages](references/course-packages.md). Author semantic JSON, validate it, then import the whole course atomically. The Vue UI renders controlled teaching components; do not generate executable frontend templates. Same-package replay is safe, changed registered content is explicitly refused. Keep legacy Markdown imports for old content or older app versions.

### Create or import course material

- Create the plan line first if it does not exist: `studyflow plan list --format json`, then `studyflow plan create --name "..." --format json`.
- Prefer Markdown with Front Matter. For `course import --file`, relative paths resolve against the CLI process working directory before service validation; when running from another checkout, pass the absolute file path inside the selected data workspace. `document read --path` instead takes a workspace-relative path.
- Before import, verify the file is inside the workspace and contains the required `course`, `lesson`, and `plan_line` metadata.
- For multiple ordered knowledge points, import lesson files in the desired sequence with the same `course`/`plan_line` and distinct `lesson` titles. Do not create a separate course per knowledge point.
- Write the lesson body for the learner: concepts, reasoning, examples and practice guidance. Keep suggested duration, textbook/PDF page numbers, scheduling instructions and Agent execution-scope reminders out of the teaching body; keep provenance/scheduling in suitable metadata or external records. Do not manufacture non-learning filler such as “first day does not need a real communication system”.
- Include `exercises` in Front Matter when practice is requested. Reading-only courses are valid when wanted; otherwise they are not practice-ready. After import, verify lesson order, `knowledge_total`, `exercise_total`, plan linkage and requested scheduling through CLI details.
- Importing an already registered path does not append newly added exercises. Do not claim such an update succeeded or edit the database to fill the gap; use available capabilities and report unsupported editing.
- Creating a course does not authorize learner answers. Simulated submissions require explicit authorization, a named isolated/demo workspace or course, and a report that they are product-test data, not learning evidence.

### Whole-course answer sheet

The UI saves/submits a course together; reviews and immutable history remain per exercise. Read `course answers get` first. Use [whole-course contract](references/course-answers.md) for exact fields, optimistic versions, stable idempotency keys and rollback. Do not loop individual submission commands to imitate an atomic course operation.

### Personal scratch notes

- Discover `course notes-get/notes-save` first. These are private per-round, per-knowledge-point scratch notes, not formal answers and never review-queue items.
- Do not treat a learner's notes as submitted homework, inspect all notes by default, or overwrite them. Read/edit only the note needed for an explicitly requested task.
- See [note contract](references/study-notes.md) for UTF-8 files, workspace-relative paths, optimistic versions and stable idempotency keys.

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

### Controlled course-workspace cleanup

- Course cleanup is destructive and requires explicit user authorization. Do not use it as a routine reset.
- Before any cleanup, export a consistency backup with `studyflow workspace export --output <backup.zip> --format json`; keep the archive outside the active course content when possible, and verify it with the advertised `workspace.validate` capability.
- Run `studyflow workspace purge-courses --dry-run --format json` first. Review the returned course, lesson, exercise, study-session, submission, review, retest, schedule-binding and document counts.
- Only after the user confirms the dry-run may an Agent call `studyflow workspace purge-courses --confirm --backup <verified-backup.zip> --format json`. The operation preserves plan lines, schema and workspace settings, and removes only course-owned records and their unshared Markdown files.
- Never replace this workflow with SQL, SQLite editing, deleting the database, or recursive deletion of the workspace. If the process cannot obtain the workspace lease or write access, stop and report the exact diagnostic instead of changing ACLs or bypassing the lock.

## Failure recovery

- Parse stderr as JSON when present. Stable errors include `ok: false`, `error_code`, `message`, and `next_action`.
- For `INVALID_STATE_TRANSITION`, inspect the parent submission and queue again; do not force a status by editing the database.
- For path or import errors, correct the file boundary or Front Matter and retry with a new idempotency key only if the first command did not succeed.
- For a timeout or disconnected process, first re-run the same read-only discovery command. For writes, use the same idempotency key before attempting a new write.
- For `DATABASE_DISK_FULL` / `WORKSPACE_DISK_FULL`, `DATABASE_READ_ONLY` / `WORKSPACE_READ_ONLY`, `DATABASE_LOCKED` or a constraint failure, stop writes, retain the original payload/key and report the diagnostic next action. Re-run read-only health checks after the environment is repaired; an uncertain write is retried with its original key, not a new one. Do not clear real data, reset a workspace or change permissions to hide failure.
- The learning UI offers return/retry/export/explicit leave-without-saving on failed, timed-out or hanging saves. A local recovery cache is best effort, not a guaranteed disk backup; an in-flight request may already have committed. Never promise that discarding rolls back a confirmed/uncertain transaction.
- If the CLI returns an internal error or the database is unavailable, stop and report the exact next action instead of modifying unrelated files.

## Reporting

Every completed operation report should include:

- command and exit status;
- IDs or paths returned by StudyFlow;
- lifecycle decision and next action;
- files changed, if any;
- validation command and result.

Read the supporting contract only when exact fields, exit behavior, or a command example is needed.


### Frozen course rounds (core learning flow)

- Discover support first. `course study-open --id <id> --idempotency-key <key> --format json` starts/resumes a local round; this is a write, not passive inspection. Do not start on behalf of a learner without authorization. `course study-detail --study-id <id> --format json` is read-only.
- Use `assignment queue` and `submission get` frozen `study_context` for review. A `markdown_path` may now contain newer material; never replace the submitted context with its live contents. `snapshot_status=LEGACY_UNVERSIONED` means no original snapshot exists; state this limitation rather than inventing one.
- Queue `batches` groups a course submission while each item remains a precise review task. `study_session_id` and `batch_id` identify the round and submission group. Waiting for review does not block ordinary course progression.
- User answers belong to one round. Authorized course answer JSON may include `study_session_id`; preserve returned draft versions and original request keys. Navigation saves drafts; only final whole-course submission creates formal review work.
- `--new-version` is explicit and only allowed after the previous round closes. Do not silently change the learner's current material or copy passed answers into a new round.
- For a retest, put a clear new problem in feedback `detail_markdown` and an actionable `next_action`; distinguish retest from correction. The learner sees it beside the original material/answer. Do not generate a fake learner answer.

### Continuous plan notes

- Default notes are one continuous plan notebook, optionally associated with a course/knowledge point. They are not answer drafts and never enter the review queue.
- For an authorized note operation read [plan notebooks](references/plan-notebooks.md) and use the advertised plan notebook CLI commands. Preserve learner blocks and versions; never fabricate learner notes or turn them into answers.
- [Legacy scratch notes](references/study-notes.md) remain supported for explicit old-data operations; do not silently migrate/delete them.


### Closed-loop and local management (app 1.7+)

Use [closed-loop contract](references/closed-loop-contract.md). A learner's correction is edited in the course, not the read-only feedback history. A new retest requires an explicit Agent-authored immutable task; never hide the question in prose. Course revisions use preview/apply without creating a second course. Plan management and notebook retrieval are versioned CLI capabilities.

Installed Skill files are bundled beside the CLI under `binaries/studyflow-agent/`. Installing/upgrading the application does not silently overwrite public Agent Skill directories or change system PATH. A public copy synchronization is an explicit, backed-up maintenance action.
