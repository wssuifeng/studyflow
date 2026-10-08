# Plan notebooks (app/Core 1.5.0 additive capability)

Read this for an authorized continuous learning-note operation. This is not the homework or legacy scratch-note contract.

## Meaning and discovery

- One `PlanLine` owns one continuous notebook. Every block belongs to the plan. Optional `course_id` and `lesson_id` are associations for filtering, not separate documents.
- Default reading covers the whole plan. Notes do not create submissions, review tasks or learning progress, and are not proof of mastery.
- Discover support with `capabilities`, then use the plan ID from a supported plan read. Do not open a course round just to get a notebook.

`studyflow plan notebook-get --id <plan-id> --format json`

The result includes `plan_line_id, version, blocks, updated_at, legacy_notes`. An absent notebook reads as version 0 / empty blocks without creating a row. Legacy per-round scratch text stays intact; copying it into the new notebook is explicit, not an automatic migration.

## Authorized update

Provide UTF-8 JSON inside the selected data workspace:

`{"blocks":[{"id":"stable-block-id","text":"A learner-authorized note","course_id":null,"lesson_id":null}]}`

`studyflow plan notebook-save --id <plan-id> --file <workspace-contained.json> --expected-version <read-version> --idempotency-key <stable-key> --format json`

This replaces the whole block list under optimistic version control. Start with the read list and preserve other blocks. Empty `blocks` intentionally clears the notebook; never use it as a cleanup or conflict workaround. The command does not authorize writing a learner's understanding on their behalf.

Each block has a unique ID (<=64 chars) and `text` (<=200,000 chars). Optional course/lesson associations must belong to the plan/course. Server-derived `scope, course_title, lesson_title, content_hash` are display/provenance metadata, not fields to invent.

An excerpt additionally requires `quote, course_id, lesson_id, source_study_id`. Quote text must occur in that frozen lesson; live Markdown is not a substitute. The server records frozen titles/hash. Original Markdown and frozen HTML are never rewritten. Prefer the UI's select-text → note operation for learner excerpts.

## Conflict / uncertain write

- Same key + identical payload returns the original receipt. Reusing a key with changed blocks/version is `IDEMPOTENCY_KEY_CONFLICT`.
- `VERSION_CONFLICT`: preserve the proposed local text and re-read. Ask for a merge/choice rather than overwrite another window/Agent. A deliberate merged update uses the new read version and a new key.
- Unknown I/O outcome: keep exactly the original payload, expected version and key; retry that request only after health recovery. A new key is not a recovery mechanism.
- Re-read the notebook after success; a saved note does not change the assignment queue or frozen study round.

## Desktop ownership

A detached note tab follows the main course while still displaying the entire plan's notebook by default. Main and tool windows share data and versions; the tool is the editor while detached, and the dock shows a placeholder. A tool window is not a new course/study round. Final whole-course answer submission stays in the main window; note saves are separate.
