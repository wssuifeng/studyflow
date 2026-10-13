# English operations · repository implementation baseline

This reference documents transport and boundaries, not permission to operate the learner. Discover methods and `system.schema` on the selected CLI. All examples use `studyflow call --method <method> --file <absolute-request.json> --format json`; Engine names are not shell commands.

## Authoring versus learning

Course validate/import and update preview/apply author content. `course.study.open` accepts optional `plan_line_id` for the actual course membership. A resumed active round retains its frozen plan: `scope_notice` does not migrate old answers/errors. English `get` returns input structure, original input and item state, not answer targets. Frozen targets/checker survive course revisions.

Learning writes use `study_session_id`, controlled IDs, returned CAS versions and stable idempotency keys. `course.english.save/check/reveal/submit/navigate/request-review` support draft, local matching, explicit assistance, whole-course confirmation, position and Agent dispute review. The ordinary whole-course answer endpoint rejects English writes. Never send `matched=true` or fabricate a learner attempt.

`course.english.retest-get/save/check` operate on an actual English task; drafts save with `expected_version`, and final checking requires the same returned version through the Engine. A completed retest is immutable; subsequent practice uses a new task. Original-item retests freeze source/checker and preserve parent/child history. Agent-authored progressive new-sentence learning uses the separate `/4` supplemental-course publication contract in [English remediation](english-remediation.md); it is not an original-item RetestTask. Discover its methods on the selected executable.

## Bounded errors

- `mistakes.notebooks`: plan/domain notebook IDs, no answers.
- `mistakes.summary/list`: specify `notebook_id`, or `plan_line_id + domain` (`general` or `english`); optional `course_id`, ISO `since/until`, `objective_id` for English, `archived`; English `view=training_errors|review_queue`.
- `list`: limit1—100, opaque `next_cursor` bound to the exact scope. Keep scope constant when continuing; restart when filters change.
- English `failed_attempts/failed_rounds` respect evidence time filters; unfiltered summary rounds are de-duplicated across the selected range, not a sum of item-rounds. List `lifetime_failed_attempts/lifetime_failed_rounds` explicitly retain lifetime counts. Failed local matches accepted by an Agent remain raw history but are excluded from `valid_error_evidence`.
- `mistakes.context`: scoped identifier, optional returned `expected_version`, limit and cursor; includes bounded frozen question, attempt/feedback and original input. Read only relevant entries, not the entire workspace.
- `mistakes.english.review.select`: authorized manual selection only, identifier/version/key. High-frequency failures do not automatically flood the review list.
- `mistakes.retest.request`: authorized original-item no-hint task, identifier/version/key. Repeated requests do not replace an active task. A completed publication receipt replays its original response.
- `mistakes.archive.preview/apply`: explicit scope, inspected `preview_hash`, stable key. Logical archive only; active review tasks are protected, original evidence is not deleted.

## Audio and failure handling

`audio.dictionary.lookup`: a frozen study/item, optional `word_index`, requested `accent=en-US|en-GB`. Target/reference visibility is checked first. Provider errors do not block text training; `accent_verified=false` is not audible validation. Current cache is bounded process-local metadata, not permanent offline audio. No TTS generation/asset import capabilities exist.

Preserve exact JSON and original key on uncertain writes. Never retry a changed answer under the old key. `VERSION_CONFLICT` means reread and preserve local input, not force overwrite. Authoring should stop on unsupported capabilities; maintenance must not silently purge/rebuild a real learning workspace to bypass active rounds.


## 1.8.0增量能力
发现实际capabilities中的/5后，可沿用原普通/英语/递进契约并增加受控小节与本地答案解析。批改参考、提示证据、计划课程位置和新字段详见[course-experience-v5](course-experience-v5.md)。不支持时不使用新字段；安装与仓库副本不自动一致。
