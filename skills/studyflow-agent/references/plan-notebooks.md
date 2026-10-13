# Plan notebook contract · format 2

## Permission and ownership

Learner notes are not assignments. Authoring courses does not authorize writing, reorganizing or cleaning learner notes. Read only the explicitly selected plan/range. One plan owns one notebook/version, not one document/version per card. Main, plan and tool windows use the same notebook; ordinary course tools expose exercises/notes, English tools expose only notes. On opening, the UI defaults to the current knowledge point, with whole-course and whole-plan selectors.

## Discovery and bounded read

Run `version`, `capabilities`, `doctor`; inspect `system.schema` for `plan.notebook.read` / `plan.notebook.apply`. An installed older build may not support these repository capabilities. Do not guess support from this Skill's version.

```
studyflow plan notebook-read --id <plan-id> --course <course-id> --lesson <lesson-id> --limit 100 --format json
studyflow plan notebook-read --id <plan-id> --entry <entry-id> --format json
studyflow plan notebook-read --id <plan-id> --offset <next_cursor> --limit 100 --expected-version <first-page-version> --format json
```

Responses include `format_version, version, entries, sources, citations, total, next_cursor`. Maximum page size100. Keep scope and version unchanged while paging; a version conflict means restart reading. A format1 read is a lossless *projection*, not an implicit write or DB conversion. Unknown future formats refuse write. Never treat a page/filtered result as the whole plan.

## Atomic commands

Create a UTF-8 JSON file within the selected data workspace. Exact minimal example:

```json
{"operations":[{"type":"insert_entry","entry":{"id":"authorized-note-1","scope":"PLAN","course_id":null,"lesson_id":null,"content":[{"type":"paragraph","content":[{"type":"text","text":"Learner-authorized note"}]}]}}],"new_sources":[]}
```

```
studyflow plan notebook-apply --id <plan-id> --file <workspace-contained.json> --expected-version <read-version> --idempotency-key <stable-key> --format json
```

Operations:
- `insert_entry`: entry has stable ID, scope `PLAN|COURSE|LESSON`, course/lesson IDs and content. Core derives title snapshots. Optional `after_id` is a same-scope anchor; null means first in that group, omitted means append in that group.
- `replace_entry`: `entry_id, content` only. It does not change ownership or other records.
- `remove_entry`: explicit `entry_id`; authorized removal only.
- `move_entry`: `entry_id, scope, course_id, lesson_id` plus optional same-group `after_id`. It changes the primary ownership, not citation provenance.

One transaction, one CAS, one receipt: any invalid node/source/anchor rejects the entire batch. Max1000 entries,1M characters,8MB document JSON,200K per entry; max2000 operations and100 source registrations per batch. Controlled blocks are paragraph, heading(level2/3), bulletList, orderedList, listItem and hardBreak; text marks are bold/italic/code/citation. Do not send arbitrary HTML, links, images, scripts or invented attributes.

## Immutable sources / editable excerpts

A source registration has `id, original, course_id, lesson_id, source_study_id` and optional `source_block_id`. Core checks against the actual frozen source, stores titles/hash and retains the immutable excerpt even if the full study snapshot is later unavailable. Never invent VERIFIED status or title/hash fields. Existing source IDs cannot be reused for changed provenance.

A text `citation` mark carries exactly `{sourceId, occurrenceId}`. The current words live in the editable document; no duplicate current_text field. Copies/splits use fresh occurrence IDs, preserving the source ID. Editing the text is allowed; Core derives ORIGINAL/PARTIAL/EDITED with NFC/newline normalization only. Punctuation/case are not ignored. Old sources that cannot be verified are explicitly LEGACY_UNVERIFIED, not silently upgraded to verified.

## Reliability / legacy guard

Same key + identical payload returns the original receipt; a changed payload/version/key reuse rejects. An unknown result must be retried with the *exact original request*. VERSION_CONFLICT requires preserving local data and comparing stable record IDs; do not blindly overwrite, clear or append duplicate records. After explicit merge, use the new version and a fresh key.

`notebook-get/save` remain format1 compatibility commands; save refuses a format2 notebook with NOTEBOOK_FORMAT_UPGRADE_REQUIRED. Never downgrade it. First apply atomically converts legacy quote+text into the same entry, retaining original blocks_json. It does not alter answers or learning rounds. JSON export preserves structure/provenance; Markdown/plain text are lossy.

Public/installed Skill synchronization, real workspace migration and learner-note updates require separate explicit permission and evidence.


Definite pre-validation rejection (INVALID_ARGUMENT or immutable/unsupported source/format) is not an unknown I/O outcome: correct the rejected content before an explicit new request. Preserve it for diagnostics/export. The desktop only preserves structured clipboard citations within the same plan and known provenance; cross-plan/other-window or external clipboard safely degrades to text with a notice. This does not claim native cross-window clipboard verification is complete.
