# 内容 / 规划层优化记录（v0.2，2026-11-12）

目标：在不改 API 合约和数据库表结构的前提下，补强“规划 → 写前核对 → 场景写作 → 审稿 → 人味 lint”这条链里的节奏、连贯和长篇记忆。
所有新字段都是**可选**的：旧书、旧细纲、mock 模式照常运行；新增的 lint 字段和 job 结果字段是附加键，前端可以忽略。

## 一、按文件说明改动

### 规划层
- `backend/app/services/outline.py`
  - 章细纲新增可选字段（模型给了合法值才写入）：`payoff_type`（爽点模式，10 种）、`payoff_level`（small / combo / milestone）、
    `hook_type`（章末钩子类型，11 种）、`strand[]`（quest 主线 / fire 感情与关系线 / constellation 世界观扩展）、`emotion`（up / down / flat）、
    `expectation`（读者期待）、`info_gap`（信息差）、`time`（故事内时间）、`must_avoid[]`；伏笔 plant 可带 `tier`（short / mid / long）。
  - 新增纯代码节奏体检 `pacing_audit()`：同一爽点模式 / 钩子类型连续 >2 章、章结果连续 yes >2 章、情绪同向 >2 章、主线连续 >5 章、
    感情线断档 >10 章、世界观线断档 >15 章、每 5 章无组合爽点、每 15 章无里程碑爽点、伏笔 >20 章未推进（黄）/ >40 章（红）。阈值为经验值，未校准。
  - `rhythm_ledger()`：最近 N 章的节奏标注；`foreshadow_age_label()`：伏笔“距上次推进几章”。
  - 滚动展开（expand）时把节奏账本、体检问题、带章龄的伏笔池喂给规划模型；`generate_outline` / `expand_node` 的 job 结果新增 `pacing_warnings`。
  - 总纲可带 `promise`（长期追读承诺），写入根节点 summary。
- `backend/app/skills/prompts/outline.md`、`expand.md`：输出 schema 增加上述字段；黄金三章按“入局 → 加压 → 承诺”、钩子递进；要求相邻章不重复爽点模式与钩子类型、超期伏笔优先安排。
- `backend/app/skills/rules/outline.md`（v0.2）：新增“节奏账本”第 8–16 条：爽点模式与强度分级、三线比例与断档红线、压扬比、3–5 条期待线、信息差、钩子类型轮换、伏笔三层级与“三段刺激”、黄金三章递进。
- `backend/app/skills/rules/chapter_plan.md`（v0.2）：新字段说明；“期待 → 压抑 → 释放”三拍；爽点铺垫/兑现/余韵分场景；场景节拍新增 `turn`（这场戏改变了什么）、`payoff_phase`、`exit_hook`；写前核对说明。
- `backend/app/skills/rules/ideation.md`、`bible.md`（v0.2）：选题要能说出至少两条长期期待线；设定库初始事实用统一键名（位置、处境、身体、境界、持有物品、已知信息、关系:X、生死…，全书级事实 entity 写“全书”）。

### 写作上下文（Context Pack）
- `backend/app/services/context.py`
  - **人物与世界当前状态**：按实体分组、关键键（位置/处境/伤势/境界/持有物品…）在前，并补上此前完全没注入的**全书级事实**（entity 为空，如故事时间、局势）。
  - **上一章结尾原文**（按整段截取 ≤300 字）：本章第一个场景从这里接，解决章与章之间位置、时间、情绪断档。
  - **长篇记忆压缩**：最近 3 章完整摘要 +“相关旧章回读”（摘要里提到本章相关实体或本章要推进/回收的伏笔的更早章节，最多 3 章）
    +“更早章节索引”（每章只取摘要首句，近处逐章、远处每 3 章抽样，总预算 600 字），上下文不随章数线性膨胀。
  - **伏笔挑选**：细纲点名的 → 与相关实体有关的 → 超过 20 章没推进的（替代原来的“最老两条”），每条带章龄。
  - **本章写作任务**：黄金三章第 1/2/3 章专属任务；按爽点模式给出执行形状（如扮猪吃虎：表面示弱 → 对手得意 → 爆发 → 反应）与三拍要求；
    期待、信息差、钩子类型、故事时间、must_avoid；最近 5 章的节奏标注（要求本章不重复）。
  - **写前核对 `preflight_check()`**（纯代码）：细纲人物不在设定库、已登记死亡的人物被要求出场、地点未登记、要推进/回收的伏笔不在伏笔池、伏笔超过 40 章没动静。
    结果写进上下文，并出现在 write-next 的 job 结果 `preflight` 里。
  - `ContextPack` 新增 `state_text`（给审稿用）和 `preflight`。
- `backend/app/skills/prompts/summary.md`：摘要按“事件 → 状态变化 → 伏笔 → 读者期待 → 章末画面”写，第一句单独概括本章（供压缩索引取用）。

### 场景写作
- `backend/app/services/writing.py`
  - 场景节拍保留可选的 `turn` / `payoff_phase` / `exit_hook`。
  - `planned_foreshadow_gaps()`：细纲要求的埋设/推进/回收在变更声明里没有对应条目 → 写入章节 warnings。
  - 审稿调用带上 `pack.state_text`；定点清理时把“章末总结”“弱化副词过量”的 lint 警告也交给 humanize。
- `backend/app/skills/prompts/scene_plan.md`：schema 增加 `turn`、`payoff_phase`、`exit_hook`。
- `backend/app/skills/rules/writing.md`（v0.2）：新增“连贯与章末”：从上一章结尾接、底账即物理规律（死人、伤势、丢失物品、认知边界）、
  章末四种断法（决定 / 发现 / 误判 / 代价），禁止总结升华收尾；变更声明的统一状态键名与“已知信息”登记。

### 审稿
- `backend/app/services/review.py`：`run_review(..., context=)` 把底账与上一章结尾交给审稿模型；新增确定性检查 `ending_issue()`：
  最后一句是总结 / 升华 / 空泛预告（“他不知道的是”“才刚刚开始”“终于明白”等）→ hook/mid，quote 取自正文，必然可校验。
- `backend/app/skills/prompts/review.md`：五个维度各给一条核对清单（前 300 字事件、章末断法、爽点三段与降智反派、认知越界、位置/伤势/物品/时间/生死连贯）。
- `backend/app/skills/rules/review.md`（v0.2）：第 8–11 条（认知越界 high、打完无收获 mid、章末总结 mid、细纲伏笔未写到 mid、must_avoid 被写出 high）。

### 人味 lint
- `backend/app/lint/banned_zh.py`：词表 123 → 155 条。新增类别：模板神态、模板心理、万能状语（“，带着一丝……”）、无情绪声线（“声音不大，却……”“语气毫无波澜”）、
  总结收束（终于明白 / 才刚刚开始 / 从这一刻开始）、告知式心理（他感到一丝 / 显得有些）、模板过渡（取而代之的是）、模板通感（淬了毒、散发着一股……气息、心里某个地方）。句式类只查叙述，台词不计。
- `backend/app/lint/humanlint.py`：新增 4 个附加指标与警告（写在 Lint 字典里，合约字段不变）：
  `weak_adverb_per_k`（缓缓/微微/轻轻/淡淡… 每千字 >3）、`subject_start_ratio`（叙述句以他/她/人名起头 >60%）、
  `sentence_len_cv`（句长变异系数 <0.40，句长过匀）、`waterfall_run`（连续单句成段 >4 段）；另检查章末最后一段的总结/升华。
  每项至多 3 分计入 ai_score。风格卡统计也带上句长变异系数和弱化副词密度。阈值为经验值，未校准。
- `backend/app/skills/rules/humanize.md`（v0.2）：上述新句式的改法、“替换不复用”、比喻先看功能再看密度。

### 测试
- 新增 `backend/tests/test_content_layer.py`（16 个用例）：细纲字段归一化、节奏体检（重复 / yes 连续 / 三线断档 / 强度窗口 / 伏笔章龄）、节奏账本、写前核对、
  状态分组与全书事实、长篇记忆压缩、伏笔挑选优先级、上一章结尾截取、黄金三章任务、伏笔计划与变更声明对账、场景字段、新词表只查叙述、新 lint 指标、章末审稿检查、规则包与提示词渲染。

## 二、思路来源（均为本次实际打开过的页面）

| 来源 | 协议 | 用法 | 借了什么 |
|---|---|---|---|
| zenstory-ai/oh-story-claudecode · story-deslop/references/banned-words.md <https://github.com/worldwonderer/oh-story-claudecode/blob/570221fb30ac1584b75018468a08c6914a16529e/skills/story-deslop/references/banned-words.md> | MIT | 改写复用 | 最毒句式（万能状语、无情绪声线、他知道、总结收束）、一级禁用词补充、弱化副词每千字 ≤3、替换不复用、比喻按功能复核 |
| lingfengQAQ/webnovel-writer · cool-points-guide.md <https://github.com/lingfengQAQ/webnovel-writer/blob/a7a102a5/webnovel-writer/references/shared/cool-points-guide.md> | GPL-3.0 | 只借思路 | 六种爽点模式、30/40/30 铺垫-兑现-微反转、压扬比、小/组合/里程碑三级强度与滚动窗口、信息差、打完要有收获、伏笔三层级 |
| XuanRanL/webnovelwriter · docs/architecture.md <https://github.com/XuanRanL/webnovelwriter/blob/main/docs/architecture.md> | GPL-3.0 | 只借思路 | Strand Weave 三线（主线 60% / 感情 20% / 世界观 20%）与断档红线（5/10/15 章）、六维审查含追读力 |
| fuxiangxu/novel-ops <https://github.com/fuxiangxu/novel-ops> | MIT | 只借思路 | 伏笔 >20 章标黄 >40 章标红、情感连续 3 章同方向强制调整、character-state 逐章追踪、句长方差衡量句长均匀度 |
| Narcooo/inkos <https://github.com/Narcooo/inkos> | AGPL-3.0 | 只借思路 | 上下文按受保护 / 可压缩分层、状态增量结算、写前意图（must-keep / must-avoid）、连续性审计对照状态 |
| 网文666《网文期待感怎么设计》<https://www.wangwen666.com/post/321.html> | 文章 | 只借思路 | 期待感 vs 悬念、3–5 条期待线、静止超过 3 章会被遗忘、三类章末钩子（信息缺口/选择悬置/后果预示）、伏笔 10/30/100 章回收 |
| 马良写作《网文黄金三章怎么检查》<https://maliangwriter.com/blog/golden-three-chapters-check-guide> | 文章 | 只借思路 | 黄金三章“入局 / 加压 / 承诺”、钩子递进三方向、弱章尾示例与四种断法（决定/发现/误判/代价） |

说明：
- GPL / AGPL / 文章来源只借思路，规则文字和代码全部自写；MIT 来源（oh-story-claudecode）的词条按本项目的正则与类别重写，已在 `banned_zh.py` 文件头与规则包 `sources` 元数据署名。
  `THIRD_PARTY_NOTICES.md` 已有 oh-story-claudecode 的 MIT 条目，本次没有改这个文件（另一位同事正在编辑），建议在该行的“用在哪里”补一句“story-deslop 禁用句式与禁用词（banned_zh.py）”。
- 搜索中还看到 YILING0013/AI_NovelGenerator 的角色状态文件、前文摘要滚动更新、悬念节奏曲线（每 3–5 章一个悬念单元）等设计，但该仓库已重构，原文件页面打不开，只看到搜索摘录，因此不列为来源。

## 三、尚未实现的想法

1. **阈值校准**：用番茄同题材头部作品算 P10–P90，替换 `pacing_audit` 与新 lint 指标的经验阈值（尤其 `subject_start_ratio`，mock 正文就有 65%，真实网文可能更高）。
2. **节奏标注回填**：mock 和旧书的细纲没有 payoff_type / strand / hook_type。可以在提交时让 summary 任务顺带输出这几项，回写到大纲节点，节奏账本才完整。
3. **伏笔层级入库**：`Foreshadow` 表增加 `tier` 与 `due_ch`，按层级算超期，而不是统一 20/40 章（需要改表，本次没动）。
4. **期待线台账**：把 expectation 做成和伏笔并列的一等实体（挂起 → 推进 → 兑现），在前端可视化，并在体检里检查“某条期待线静止超过 3 章”。
5. **认知边界程序检查**：用 `known_by` 和“已知信息”事实，检查对白里有没有角色说出了他不该知道的作者真相名词。
6. **弧 / 卷级冻结摘要**：弧写完时生成一段弧摘要存入弧节点 summary，替代现在的“首句索引”，进一步压缩百章以上的上下文。
7. **套路冷却期**：记录已用桥段（退婚、拍卖会、宗门大比…），冷却期内再用必须换显著变体（novel-ops 的 used-tropes 思路）。
8. **多读者画像预评**：前三章用 4–6 个读者画像做弃读点预测（架构文档 v0.2 计划）。
9. **lint 替换产物复查**：定点清理后，对新文本单独跑一次“替换词重复”检查，防止“垂下眼”这类替换本身变成新口癖。
