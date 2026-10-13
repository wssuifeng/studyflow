# Structured course packages (course-package/1 and /2)

Read this when authoring a new multi-knowledge-point course. Discover `course_package_validate` and `course_package_import` first; older installed Engines cannot render the new components. Use the matching application candidate or keep legacy Markdown.

## Workflow

1. Confirm workspace/doctor and inspect existing plans/courses; create the named plan only if missing.
2. Author a UTF-8 JSON file using [the complete sample](../examples/course-package.json). This is an input document, not executable UI code. Keep private course packages outside the public source repository.
3. `studyflow course validate-package --file <absolute-package.json> --format json` validates without creating a service, workspace, files, or database. Check `ok`, `valid`, counts and title.
4. `studyflow course import-package --file <absolute-package.json> --format json` validates the whole package and registers all lessons/exercises in one transaction. Read its exit status and JSON.
5. Read `course detail --id <returned-id>`, `plan detail`, and `today`. Verify order, blocks, question counts and plan linkage. Do not call `study-open` or create answers without authorization.

The importer writes immutable, portable Markdown under workspace `content/course-packages/<package_id>/<content_hash>/`, with structured metadata and a linear fallback. Agents do not need to create/edit those generated files. This is not a Markdown editing task for the learner.

Same package ID and identical content safely return `created=false` and the existing course ID. Changed content under the same ID returns `COURSE_PACKAGE_CONFLICT`. Existing same-title courses return `COURSE_ALREADY_EXISTS`; never use a new ID to silently overwrite or append to them. For an explicitly authorized in-place revision, discover and use `course.update.preview/apply` through the neutral `call` transport. Preserve stable IDs and inspect the preview; do not create renamed duplicates or restart frozen rounds to bypass revision protection. `COURSE_PACKAGE_BUSY` means another publisher is active; retry the same input after it finishes. On uncertain writes inspect before retry; do not delete data or reset the workspace.

## Shape

- Top-level required fields: `schema: "studyflow.course-package/1"`, `package_id`, `plan_line`, `course`, `lessons`.
- `course`: required `title`; optional `summary`, `subject`, `difficulty`. Summary belongs to the plan/path page, not every knowledge-point body.
- `lessons`: 1–50 ordered objects with `id`, `title`, `blocks` and optional `exercises`.
- IDs: lowercase letter first, followed by lowercase letters/digits/underscore/hyphen, at most 64 characters. Lesson IDs unique per course; block and exercise IDs unique within their lesson. Keep IDs stable when referring to the same semantic content.
- `blocks`: 1–80 per lesson; `id`, `type`, `title` are required. Unknown types/fields are rejected.
- `exercises`: 0–100 per lesson. Each requires `id`, `title`, `prompt`; optional `requirements`, `type` (default `SHORT_ANSWER`, discover supported existing exercise types). Practice references use these local exercise IDs, not database IDs. The importer maps them to registered exercises.
- File maximum 4MiB. Missing references, duplicate JSON keys, uneven table rows, wrong field types and invalid versions reject the whole package.

| type | Additional fields | Teaching use |
|---|---|---|
| concept | `body` | Explain a concept in continuous prose. |
| comparison | `columns: string[]`, `rows: string[][]` | Compare on shared dimensions; 2–6 columns, 1–50 rows. |
| steps | `items: [{title, body}]` | Ordered process, 1–20 steps. |
| example | `given`, `steps: [{title, body}]`, `conclusion` | Worked derivation with assumptions and reasoning. |
| callout | `body`, optional `tone: note / warning / tip` | A specific misconception, boundary or useful tip. |
| summary | `items: string[]` | 1–20 conclusions worth recalling. |
| practice | `exercise_ids: string[]` | Open the existing same-round answer sidebar, not another answer model. |

Only rich-text `body`, `given`, `conclusion` support Markdown fragments (including code fences); HTML is sanitized, not executed. Titles, table cells and summary items are plain text. Do not supply CSS, SVG source, Vue templates, scripts, layout coordinates or fake interaction state. The UI owns rendering.

## Authoring quality

Choose components to suit the knowledge, not to satisfy a checklist: a CPU lesson can use comparison and steps; a numeric lesson should show assumptions, bit width and a worked derivation. Never pad every lesson with all seven types. Write substantive explanations, not just headings or tables. Keep essential reasoning visible; do not turn the course into decorative cards. No timing, textbook page references or Agent process instructions inside teaching blocks; keep provenance in external authoring records. Exercises must state meaningful constraints. Do not put solution text for assessment questions into the prompt or practice link.

A new round freezes content blocks and exercise references. Existing rounds/answers remain tied to their captured version. Notebook excerpts may include `source_block_id` with the frozen `source_study_id` and lesson ID; the service verifies that the quotation is actually in that block. Do not invent notes or mastery.

## English extension: course-package/2

The current source accepts `/1` for general courses and `/2` for general or English. Discover `capabilities.content` on the actual executable first. `/2` adds optional `course.learning_mode` (`general` by default); an English course requires `english` on each exercise. `/1` rejects `learning_mode` and English extensions. An English lesson must contain at least one exercise; all courses have at most 500 exercises.

The English extension is described in [english-course-authoring](english-course-authoring.md), with a complete [synthetic sample](../examples/english-course-package.json). Do not add arbitrary media URLs, frontend layout, assessment results or lifecycle statuses to an authoring package. Legacy `/1` examples remain valid. Current source does not permit changing an existing course's learning mode in place.


## /3: visible summary, folded supplementary detail

Only when capabilities.content.course_package_schemas includes `studyflow.course-package/3`, use /3. It supports existing general/English modes (course.learning_mode), the seven original blocks plus:

```json
{"id":"binary-detail","type":"details","title":"位权为什么是二的幂","summary":"相邻两位的位权相差两倍。","body":"### 推导\n每一位只有 0 或 1，向高位进位后表示两个低位单位。"}
```

Required non-empty fields: stable id, type, title (200 characters), summary (3,000), body (20,000). No nested blocks, default_open, arbitrary HTML templates, CSS or script fields. UI defaults closed, but title/summary are visible; core definitions and exercise requirements must stay outside folded detail. Markdown fallback/export contains all text. Old /1 and /2 remain strict and do not accept details. A capable Core still reads old packages/rounds; do not falsely promise old executables will import /3.

A complete synthetic example is [course-package-details.json](../examples/course-package-details.json). Validate with CLI before importing. Current rounds remain frozen after revision. Default concept layout is linear; use the explicit comparison block for semantic comparisons rather than asking the author to combine unrelated concepts into a huge body.

## Package /4: explicit English progression

`studyflow.course-package/4` retains /3 teaching blocks and existing general/English shapes. Only /4 accepts `english.progression` with required `chain_id` and `stage`; earlier /1–3 retain strict field whitelists. Stage order is vocabulary → chunk → pattern → variation → transfer; multiple items per stage and chain are allowed. See [supplemental authoring](english-remediation.md) for extra publication constraints and the difference between generic MAIN import and SUPPLEMENT preview/publish. Do not silently upgrade old packages or current frozen rounds.


## 1.8.0增量能力
发现实际capabilities中的/5后，可沿用原普通/英语/递进契约并增加受控小节与本地答案解析。批改参考、提示证据、计划课程位置和新字段详见[course-experience-v5](course-experience-v5.md)。不支持时不使用新字段；安装与仓库副本不自动一致。
