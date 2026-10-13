# 按计划取词、持久小表与阶段回访

用于获授权的现有词表；不要先全库AI分类、拆字母页或填完全部缺口。母表只读，从当前目标有目的查询并逐步积累小表；完整范围由阶段性摘要/未覆盖候选检查持续治理。

## 1. 取用规则

先定当前阶段/目标、可用基础和不引入内容，后查询候选。按本课词义/用途分新内容、先修、复习或词族扩展。先修证据未知就写未知，不能把参考项目的第一课当本学习者已知。

小表绑定阶段目标群/课程主题/明确补强任务，可支持一节或少量连续课；不要求教完文件。相关已有表优先复用，多义词另选本课义项，来源事实不反复复制手工维护。专业词可优先桥接当前课程，超考试范围项另标专业补充，不扩大官方覆盖统计。

词族父项要出处；去后缀仅给候选。缺释义/音标/关系按当前必要项核实，缺口留母表；词典无音频不虚构，TTS不属于这套工具。现有AI补释义是作者来源，不等同官方词典。

## 2. 来源身份和查询接口

自带工具：scripts/authoring_workspace.py，Python3.10+标准库。不依赖Core/Engine、不打开数据库，也不是新的studyflow子命令。独立复制整个Skill后同样可用；无Python时只做有界人工选择/蓝图，不自行安装或称工具已运行。

指定`--root <作者资料根>`，不能是AppData数据根。`--source base=词表/base.tsv`可以重复，路径必须在根内、不能链接。源支持UTF-8四列TSV：word/phonetic/meaning/origin，中文列音标/释义/来源可替代；不自动猜其它格式。source_id要长期固定，否则条目ID随标识变化。entry_id由来源标识+原词形生成，排序/释义变化不改ID；词形纠错要保存旧→新关联。

命令示例（把脚本路径替换为实际加载Skill目录）：

```powershell
python -X utf8 "<skill-root>/scripts/authoring_workspace.py" --root "<author-root>" query --source "base=词表/base.tsv" --word read --word data --limit 20
python -X utf8 "<skill-root>/scripts/authoring_workspace.py" --root "<author-root>" query --source "base=词表/base.tsv" --contains "数据" --limit 20
```

输出含稳定ID、完整释义/来源、原行、母表hash和有界items。默认limit20，上限60；默认max_chars16000，上限32000。单条超预算拒绝，不截释义。筛选改变/源内容改变后旧cursor拒绝。没有条件时拒绝查询；`--browse --purpose "有限检查理由"`仅用于候选检查，不按返回顺序教课。

## 3. 生成一个版本化小表

1. 从query返回的sources/entry_id构造recipe：format=1、selection_id、正整数revision、stage_id、objective、sources（原id/path/hash）、items。
2. 每项有entry_id、role=new/prerequisite/review/family、sense、reason、meaning_verified=true、evidence_refs列表；词族项另有family_source_ref。确认只表示作者复核声明，不是程序自动质量判定。参考[合成选择样例](../examples/vocabulary-selection.json)，条目ID/hash需用真实查询结果替换，不能照抄占位。
3. 源hash必须一致，空释义不能选为可用项；未知ID/重复项/未复核拒绝。工具不补缺口、不重写母表。
4. `select --recipe <根内JSON> --output <根内新版本目录>`写words.tsv、selection.json、manifest.json。前者为人类可读投影、后者为选择依据/版本校验；不用手工改生成表。单表上限60项/12000字符，按有意义子目标减量，不是每课配额。
5. 原目录内容不覆盖；完全相同选择原路径重跑返回created=false，载荷不同必须新revision/目录。未知已有目录、被改动产物拒绝。新目录独占创建，manifest最后发布；中途故障留下未提交目录时不自动覆盖/清理，人工核对后用新版本路径继续。相同selection_id/revision不得存不同内容。

课程目标、题面、所用材料版本在课程蓝图记录；简单选择不需要复制第三份完整词包。已发布来源快照保护冻结轮次，未来释义变化列受影响课程，不静默替换。

## 4. 长期遗漏检查与回执关联

`coverage --source ... --selections-dir <根内小表父目录>`只扫描这个目录的直接子版本，输出来源记录/去重拼写/已选/未选/释义缺口/过时版本数，不输出全量剩余词。该工具不是掌握数据库，也不把“已选”称作“已学”。历史不同源版本单独报告排除，不能直接解读计数下降为遗忘。

`query ... --browse --purpose "阶段遗漏候选检查" --exclude-selections-dir <同一父目录> --limit 20`返回少量当前源版本尚未选项，可用cursor分批检查。有用候选须重新按目标选，不把检查游标当课程顺序，不为追求覆盖强教当前无关词。

获授权实际导入后，保存真实`course detail --format json`回执，再`link --selection <版本目录> --receipt <回执JSON> --course <实际ID> --content-revision <实际版本>`登记关联。要求ok=true、course.id/content_revision一致并保留receipt hash；后续范围检查发现回执变化/丢失拒绝。它只校验文件/字段一致，不能认证回执来自CLI；Agent必须实际运行CLI并检查退出码，禁止伪造文件。导入关联明确learning_evidence=false。

## 5. 阶段闭环与维护

每阶段收口看目标真实证据、已选未用、已发布未检验、长期未结项以及范围偏向。当前目标/证据由[工作区治理](learning-workspace-governance.md)维护，事实与关系标签只逐步建立；不把全部词列进阶段。

派生/多义词/跨表同拼写不凭文字自动合并，合理复用不算新覆盖。当前阶段满足标准就关闭，后续有限承接；学习反馈调整选词和新增负荷，不不断搬动静态词表分类。

无引用可再生临时稿/缓存按授权清单清理；母表、ID关系、发布依据/来源和必要回执不是垃圾。工具不代清理、不读其它目录、数据库、模型凭据或网络，不负责更新真实课程。
