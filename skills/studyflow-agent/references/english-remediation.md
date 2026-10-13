# Error-driven English supplemental learning

Use only after discovering the running CLI's package `/4`, `course.remediation.preview/publish/list/get`, and scoped mistake queries. Older binaries must not be treated as supporting them merely because this Skill was updated.

## Scope and teaching decisions

Select the confirmed plan and, where useful, course/time/objective scope. Read `mistakes.summary/list`, then limited `mistakes.context` evidence for selected English aggregates. Preserve `aggregate_id`, its returned version, and selected valid evidence IDs. Do not scan all answers or infer grammar deficits from one typo, an engine failure, or failure counts alone. Separate observed mismatch from a proposed explanation; consult frozen prompts, accepted answers, correction history and objectives. Agent-accepted alternative expressions are not usable error sources.

Consolidate related sources by a narrow learning objective, rather than creating one course per incorrect sentence. Keep supplemental learning separate from the main curriculum and from original-item retests. A supplemental course may reference several sources; later distinct learning requests may reuse sources with a new explicit package identity. Do not recursively create more courses when the supplemental course itself produces errors.

## Progressive content

Package `/4` uses the existing English Course/Lesson/Exercise shape plus optional `english.progression={chain_id,stage}`. Allowed ordered stages: `vocabulary`, `chunk`, `pattern`, `variation`, `transfer`. Supplemental publication requires a progression value on every item and, in each chain, necessary vocabulary, a pattern and a final transfer stage. Repeated items in the same stage are permitted; do not move backward inside one chain. Use a new chain for a new sequence.

The author chooses the instructional substance: introduce necessary words and reusable chunks before combining them; explain the targeted rule before use; vary known subjects/objects/context instead of introducing several unknown structures at once. New words must be introduced or verified prerequisites, not silently inserted into a supposedly independent check. Do not copy reference project courses. Prefer a small coherent sequence; the maximum input limits are not desired lesson sizes.

Keep necessary definitions visible in teaching blocks. Optional deeper reasoning can use `details`, supported by `/4`. `transfer` items use distinct wording to test the same objective without copying the original source sentence. Targets/accepted variants and natural Chinese cues must agree with token/checker limits. Assisted results, course completion and independent transfer results are distinct; none prove long-term mastery or resolve the original mistake automatically.

## CLI contract

Store the package and request JSON in the approved data workspace. Package validation remains read-only. Preview/publish fields:

- `plan_line_id`: selected plan; the package's plan name must match it.
- `path`: package path within this workspace.
- `objective_ids`: 1–5 unique identifiers, present in the course's training objectives.
- `rationale`: concise goal, evidence-based reason and prerequisite assumptions, at most 4,000 characters; not an unverified diagnosis.
- `sources`: 1–30 aggregates, each `{aggregate_id, expected_version, evidence_ids}`; 1–10 unique valid evidence IDs per aggregate. Obtain real IDs from `mistakes.context`, never invent them.
- Publish adds the returned `preview_hash` and a stable `idempotency_key`.

Call `course.remediation.preview` first. On authorized publication, use the unchanged package/request plus the preview hash and stable key with `course.remediation.publish`. Publication atomically creates the course, SUPPLEMENT membership and provenance references. Normal `course import-package` creates a MAIN membership and is not a substitute. Source changes, wrong scope or accepted/archived evidence require reconsideration/another preview, not bypassing checks. Unknown write results retain original payload and key; read back or repeat the same request, never allocate a fresh key automatically.

Read `course.remediation.list` with required `plan_line_id`, optional `source_course_id/aggregate_id`, and bounded `limit` (1–100), `offset`; use `next_offset`. `get` gives objectives, source references, learning status and independent-transfer summary, not another stored answer copy. `COMPLETED` is course completion; `UNASSISTED_PASS` is the current round's transfer result; original-item retests remain independent. UI uses full English training; its only side tool is plan notes.

## Example and verification

[Progressive package](../examples/english-remediation-package.json) is synthetic content, not learner material. Create real sources only from authorized existing error evidence. Validate, preview, publish and read back real CLI receipts. Do not open a learner round, fill answers or manufacture errors to make publication work. Source/provenance changes are controlled; a progressive revision cannot silently drop its protocol/objectives. Public and installed Skill copies require separate synchronization authority.


## 1.8.0增量能力
发现实际capabilities中的/5后，可沿用原普通/英语/递进契约并增加受控小节与本地答案解析。批改参考、提示证据、计划课程位置和新字段详见[course-experience-v5](course-experience-v5.md)。不支持时不使用新字段；安装与仓库副本不自动一致。
