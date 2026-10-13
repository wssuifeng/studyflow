# 课程包/5：课文小节、解析与计划课程治理

先发现content.course_package_schemas、system.schema及实际方法。app/Core1.8.0、Skill2.7.0是本批身份，能力发现仍是准入标准。

## 内容小节
/5继承/1—/4普通/英语/details/progression。concept的body与sections二选一。section的id/title/role/body必填，summary在supplement必填，children可选。main常显、supplement摘要常显/详解折叠；最多两层、每块共40小节、摘要和正文合计20000字符，ID在块内全树唯一。必要定义/条件不能折叠隐藏。不写脚本或布局字段。

## 题目与本地解析
/5题目可含review_reference={answer,explanation,criteria,accepted_variants?,source?}。answer/explanation各最多20000字符，criteria1—30项，accepted_variants0—30项，每项最多3000字符，source最多3000。结果、推理、合格条件及出处分别表达；合理等价表达不照抄强判错。prompt/requirements只含任务，不泄漏结论。这是用途分离，不是账号权限。

参考随CourseRevision作者包与学习快照固定。默认学习DTO不附答案；用户展开调用exercise.reference.view记录提示，Agent用只读exercise.reference.read，不能混用。缺失available=false，不生成未经核实解析。

定位二选一：{study_session_id,exercise_id}或{submission_id}，可带reference_revision选择不可变课程内容版本。返回content_revision/frozen_content_revision/question_hash/reference_hash。更正版只接受与冻结题面指纹相同的版本；同题ID改题拒绝。通过正常course.update.preview/apply更正参考，新轮次读新版，旧轮次读原版。

review.write可传reference_hash、reference_revision、reference_reason；先只读回读再填。更正版必须有原因。未传hash的旧客户端仍兼容，但依据未记录，不认证其已核对。独立复测任务不复用原题解析，读取任务自身依据。

## 计划课程位置
plan.edit新增COURSE_POSITION，values={course_id,position:"NORMAL"|"OTHER",reason?}，OTHER要求原因。复用expected_version/idempotency_key。plan.detail返回learning_group=PENDING/COMPLETED/OTHER。完成指本计划学习提交，不等于批改通过或掌握。其他保留历史、取消未来未执行日程；恢复不自动重建日程，不用于删除或规避错题。

## 有界证据和笔记
learning.evidence必填plan_line_id；course_id/learning_mode可选，limit1—100默认20，cursor用next_cursor。每轮最多20题摘要，不带全部正文/答案；可继续翻页与按ID读上下文。提示追踪只覆盖新轮次，旧信息legacy_unknown；mastery不自动推断。不要代作答或开启轮次制造证据。

笔记new_sources可附source_section_id（须有source_block_id），核对摘录属于冻结小节。course.source.read可带block_id+section_id定位，仍只读。

示例：[合法/5课程](../examples/course-package-v5.json)。发布要逐题语义复核、实际Vue呈现、CLI回读；结构校验不替代教学/学习验收。真实旧课更新保留稳定ID/冻结历史，不重建或清理来换排版。
