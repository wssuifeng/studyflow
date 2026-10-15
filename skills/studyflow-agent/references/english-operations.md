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


### 1.8.1交互与词典时序补充
词典lookup即时返回受控发音地址及课程辅助信息；网络音标/释义在有界后台读取，metadata_status可为loading/ready/unavailable/deferred/not_requested。后台失败不表示训练保存失败；同词请求去重、失败短缓存，不阻塞CLI/Engine写入。不得为了获取词典辅助而显示用户输入作为标准答案。

Ctrl+Quote在当前词位上方显示提示、Ctrl+Semicolon显示本句提示，不替换输入编辑器；查看仍写辅助证据。快捷键不抢笔记/IME/重复按键。自动保存允许继续输入，切项先等在途请求及最新输入确认；未知写入仍保留原幂等键。
键音是本地反馈，与网络朗读分开；可按用户选择导入本地短音频，不把第三方音频或其私人路径写进课程包或公共仓库。

## 1.8.2 /6训练增量

/6继承/5，新增受控sentence_parts与不同词数完整accepted_answers；新即时训练只local_exact。历史agent数据在现有target/accepted范围内可以本地检查，已等待审核/已通过的历史答案仍保留；前端不再提供新审核入口。检查结果返回error_count，默认连续两错或Ctrl+Semicolon显示解析，正确后不渲染。听音read可在作答前解析冻结目标，不能据此宣称已查看文本解析或已掌握；文本答案read仍要求已通过/显式提示。

Ctrl+Quote整句朗读、Ctrl+Shift+Quote当前词、Ctrl+Semicolon解析、Ctrl+Period暂跳/正确后下一项、Ctrl+Comma上一项。所有词位完整时Enter从当前词直接检查，Space仍向下一词。自动朗读默认进入项/检查结果各一次。所选词典口音失败后，可在同一受控词典尝试另一口音一次并明确通知，不修改用户口音偏好、不冒称已验证该口音；两次失败才尝试本机英文声音即时兜底。本机声音也可能启动失败（例如synthesis-failed），应明确未播放；不把可枚举声音或地址返回当成功。

整课完成先只读回查，存在空白/暂跳/未通过项先navigate第一缺项、不submit；服务端仍验证全课，不能通过客户端进度绕过。未知提交保持原幂等键；确定COURSE_INCOMPLETE不作为未知保存失败持续锁住退出。


## 1.8.5 incremental capabilities (discover the installed schema first)

`audio.dictionary.metadata` reads the current frozen item's per-word auxiliary metadata without playing audio or waiting for provider HTTP. Missing/unknown phonetics are allowed; returned word phonetics do not certify accent or sentence transcription.

English evidence-free rounds may use the existing restart preview/restart flow. A preview includes `expected_training_version`; pass it unchanged together with `expected_version`, source hash and a stable idempotency key. Browsing/navigation alone may be allowed. Any saved input (even an empty saved draft), text reveal, check, completed training or unknown write blocks abandonment. Preview does not authorize restarting a learner's actual round.
