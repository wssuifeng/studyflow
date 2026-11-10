# Agent协作工作区结构与记录规范

本规范只管理独立的Agent协作资料根。StudyFlow课程、学习、提交和批改的事实仍以CLI回读为准；协作区保存计划依据、原始参考资料、作者产物和可追溯的最小证据，不替代数据库。

## 1. 标准目录与权威文件

```text
StudyFlow-Agent-Workspace/
|-- AGENTS.md                         # 边界、必读顺序、持久规则
|-- INDEX.md                          # 当前指针和导航，不复制详情
|-- state/
|   |-- current.md                    # 本轮状态快照、阻塞、下一步
|   |-- goals.md                      # 目标索引、状态和完成日期索引
|   `-- decisions.md                  # 用户确认且仍有效的决定
|-- goals/GOAL-YYYY-NNN/goal.md       # 用户定义目标及完成证据
|-- plans/PLAN-YYYY-NNN/plan.md       # 计划、阶段、课程序列与引用
|-- references/README.md              # 参考资料总索引
|   `-- REF-YYYY-NNN/
|       |-- README.md                 # 来源、版本、哈希与适用范围
|       |-- usage-log.md              # 每次阅读/引用的记录
|       |-- originals/                # 用户提供或获准保存的原件
|       `-- extracted/                # 明确标注的OCR/摘录/转换稿
|-- course-archive/
|   |-- README.md
|   |-- drafts/PLAN-ID/COURSE-SLUG/vNNN/      # 未发布作者源包
|   `-- published/PLAN-ID/COURSE-ID/revNNN/   # 已发布不可变快照与回执
|-- records/
|   |-- README.md
|   |-- sessions/YYYY-MM-DD-topic.md
|   |-- learning/YYYY-MM-DD-COURSE-ID.md
|   `-- grading/YYYY-MM-DD-COURSE-ID-event.md
`-- <materials-root>/                 # 可选：用户指定任务资料，由AGENTS说明边界
```

路径名中的`YYYY-MM-DD`使用实际本地日期。`GOAL-YYYY-NNN`、`PLAN-YYYY-NNN`、`REF-YYYY-NNN`是协作区内稳定的人类索引号；按既有最大序号递增，永不复用。它们不是StudyFlow业务ID。`plan_line_id`、`course_id`、`lesson_id`、`exercise_id`、`study_session_id`、submission/review ID必须原样采用CLI返回值，不能自行生成或改写。

现有协作根不必为符合树形示例而整体搬迁。优先补齐缺少的职责文件与索引，保留既有历史和链接；新建文件沿用已存在的等价目录，避免形成第二个权威状态。

## 2. 文档职责与字段

- `AGENTS.md`：说明协作区用途、三类根目录、每次会话必读顺序、CLI唯一业务数据边界、允许保存内容和隐私禁区。它是操作约定，不放每日状态。
- `INDEX.md`：链接当前状态、活动目标/计划、最近session/learning/grading记录、参考资料索引和课程归档。只放短指针。
- `state/current.md`：记录更新时间、当前目标/计划/课程、已验证的关键CLI事实及日期、未做事项、阻塞和下一步。过期时标注待复核；不得把过去版本说成当前。
- `state/goals.md`与`goals/GOAL-.../goal.md`：索引和详细目标分开。目标原文由用户定义；含`created_at`、用户指定的`target_date`（无则空）、可观察的`success_criteria`、关联计划/CLI ID、状态、证据来源和`completed_at`。只有逐条满足事先定义的条件且有用户确认或可核验记录时才填写实际完成时间；仅学过、发布课程或单次答对不自动算目标完成/掌握。
- `plans/PLAN-.../plan.md`：关联目标、已知基础/未知项、有限阶段和退出条件、课程顺序与实际`plan_line_id`、参考`REF-ID`、学习证据、下一步、排除范围。滚动细化下一课或小批课程，不用无限加课延长目标。
- 每个`REF-ID/README.md`：标题、作者/机构、来源路径或URL、版本/发布日期、获取日期、原件文件名与SHA-256、授权/可用范围、相关目标/计划、提取方法与已知缺陷。来源原件只读保存；OCR/摘录写入`extracted/`并关联原件，不覆盖原文件。没有获准保存的网络资料只登记稳定来源与访问日期，不擅自下载。
- `REF-ID/usage-log.md`：每次实际阅读/使用一条记录：日期时间及时区、会话记录链接、文件名和hash/版本、实际读到的页码/章节/范围（不夸大为全文）、用途与关联GOAL/PLAN/课程、具体采用的事实/定义/例题或“本次未采用”、产出位置、疑点/核实状态。后续会话复用资料也记录本次读取；单纯看到文件名不算已阅读。

记录说明模板和完成闭环见下节及[长期工作区治理](learning-workspace-governance.md)。

## 3. 课程版本、学习证据与批改记录

- `course-archive/drafts/`保存未发布蓝图、源包、依据清单、审核问题与验证回执。每个候选使用新`vNNN`，写入关联目标/计划、主题、输入参考REF-ID、状态和SHA-256；不得把草稿写成已入库课程。
- `course-archive/published/`只保存CLI确认成功的版本。归档实际提交的包字节、SHA-256、CLI命令/能力、成功回执、返回的course ID/content revision、计划归属和readback结果。新revision新建目录，旧快照不覆盖；失败/冲突/不确定回执单独记录，不伪装发布成功。
- `records/learning/`在本会话确实从软件读取并将其用于目标/计划/制课时建立。记录读取时间、CLI版本/能力或命令、查询范围、返回的稳定ID、course content revision/study session ID、提交/练习状态、分数或错误类别等必要摘要、证据局限、它影响了哪一项计划决定。不复制答案原文、完整题面、私人笔记或与任务无关的整课导出；不足以判断的写“未知/证据不足”。
- `records/grading/`每次实际批改/反馈写入都必须留记录：来源submission/exercise/course ID、冻结内容版本、操作日期、使用的CLI能力及幂等键（可脱敏但必须能安全对账）、CLI返回review ID/状态/分数或反馈摘要、读回确认、失败/重试/未决项。只看队列时记录为只读查看，不伪装成已批改。保留原答案和历史仍由StudyFlow管理；协作区不复制答案正文。
- `records/sessions/`记本次目标、读取了哪些REF与CLI证据、实际修改/写入、验证回执、未执行/未验和后续动作。状态摘要更新到`current.md`，不要把整份对话逐字存档。

## 4. 制课与学习的长期闭环

```text
用户定义目标与完成条件
  -> 建立有限计划/阶段并关联已登记参考
  -> 恢复相关学习证据，选择下一课与检验
  -> 草稿与来源归档
  -> 结构校验 -> 内容/事实审核 -> 实际界面渲染
  -> 获授权后经CLI发布并readback，保存不可变版本
  -> 学习者实际学习后，经CLI读取有界学习证据并归档
  -> 按真实提交批改，保存批改回执与结论
  -> 评估目标条件，更新计划/下阶段
```

三道课程质量关不能合并：

1. **结构校验**：由当前CLI支持的package/schema validation检查字段、引用和约束；通过只证明结构合法。
2. **内容审核**：作者按授权来源检查事实、先修、解释、题目与参考。`course quality-check`是只读顾问，会读取输入包及可选validation/rendering receipt，不会替代作者判断或执行渲染。
3. **真实渲染**：由实际StudyFlow桌面端或真实浏览器中的StudyFlow Vue界面加载确切候选/已发布revision后检查。记录宿主/App版本、CLI数据根或隔离根、course/revision或候选SHA-256、主题/视口/缩放、实际滚动区、检查范围、截图路径与hash、问题和结论。截图必须来自真实宿主；手写HTML、静态mock、包校验、quality-check输出都不是渲染证据。

本轮CLI实测若没有渲染/截图能力，就由外部真实渲染器产生可追溯回执；`--rendering-receipt`只是把回执交给质量检查读取，不代表quality-check自己渲染。先核实当前CLI对回执JSON的格式；格式不明或没有真实宿主时，标记“真实呈现未验”，不得自造格式/截图或报通过。三道关分别记结论、时间、对象版本和证据链接。

## 5. 每次会话与新资料记录

新会话必须读协作区状态、当前活动计划及最近相关session/learning/grading记录。数据会变化时，以本次CLI返回事实纠正状态，并记清楚来源日期；不能只读旧日报后推断当前课程进度。实际读取的每条学习证据应建立/更新learning记录，批改操作必须写grading记录；结束时关联到目标和计划，使下一课设计能看到“为何选这课、证据是什么”。

用户提供新资料时：先确认资料根和适用目标/计划；按`REF-YYYY-NNN`登记元数据与hash，保留原件并区分提取稿；实际打开阅读后立即追加使用日志，再把关键依据引用到草稿/审核记录。资料缺少来源、版本或可信度时明确标注，不将生成摘要当原始出处。没有新资料时继续使用既有登记资料，并记录本次读取到的范围，避免会话更换后误称已复核全文。

目标结束时记录实际`completed_at`日期时间和时区、满足条件的证据链接、确认者；若条件未全部满足或只有推测，保持进行中/待核实。旧记录保留，新状态以索引链接和更新时间表达，不静默删除失效依据。
