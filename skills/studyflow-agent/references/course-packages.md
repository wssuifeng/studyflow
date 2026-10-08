# Structured course packages (course-package/1)

Read this when authoring a new multi-knowledge-point course. Discover `course_package_validate` and `course_package_import` first; older installed Engines cannot render the new components. Use the matching application candidate or keep legacy Markdown.

## Workflow

1. Confirm workspace/doctor and inspect existing plans/courses; create the named plan only if missing.
2. Author a UTF-8 JSON file using [the complete sample](../examples/course-package.json). This is an input document, not executable UI code. Keep private course packages outside the public source repository.
3. `studyflow course validate-package --file <absolute-package.json> --format json` validates without creating a service, workspace, files, or database. Check `ok`, `valid`, counts and title.
4. `studyflow course import-package --file <absolute-package.json> --format json` validates the whole package and registers all lessons/exercises in one transaction. Read its exit status and JSON.
5. Read `course detail --id <returned-id>`, `plan detail`, and `today`. Verify order, blocks, question counts and plan linkage. Do not call `study-open` or create answers without authorization.

The importer writes immutable, portable Markdown under workspace `content/course-packages/<package_id>/<content_hash>/`, with structured metadata and a linear fallback. Agents do not need to create/edit those generated files. This is not a Markdown editing task for the learner.

Same package ID and identical content safely return `created=false` and the existing course ID. Changed content under the same ID returns `COURSE_PACKAGE_CONFLICT`. Existing same-title courses return `COURSE_ALREADY_EXISTS`; never use a new ID to silently overwrite or append to them. For an explicitly requested revision, use a new package ID and a clearly versioned course title. General in-place course updating is not implemented. `COURSE_PACKAGE_BUSY` means another publisher is active; retry the same input after it finishes. On uncertain writes inspect before retry; do not delete data or reset the workspace.

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
