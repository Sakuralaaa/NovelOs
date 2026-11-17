# AI 写长篇小说：对标调研与 NovelOS 改造建议（2026-11-17）

标注：【核实】=本次打开原页面/源码确认；【厂商自报】=厂商自己的实验数据，未经第三方验证；【推断】=我的判断。星数为 2026-11-17 GitHub 搜索结果。

## 一、商业产品

**Sudowrite**：Story Bible 按 Braindump→梗概→类型/文风→人物→世界观→大纲→场景→成稿 逐级生成；Write 续写前会先读前文最多 2 万词再加上 Story Bible；自研小说模型 Muse，官方称"训练中专门度量 AI 套话并系统去除"，文风靠最多 1000 词的 Style Examples 样例来定，不靠写规则【核实】。最有用：**文风用样例来定，不用一堆规则和禁令。** https://sudowrite.com/blog/how-sudowrite-works ，https://docs.sudowrite.com/using-sudowrite/1ow1qkGqof9rtcyGnrWUBS/sudowrite-muse/4k9bFDMSyic6mFPkYFHrkZ

**Novelcrafter**：节拍（beat）就是一串"然后"，每章是一个有目标的小弧；只把节拍和前文里提到的设定条目、POV 人物、全局条目、关联条目注入上下文；AI 套话清单（AI-isms）的用法是在稿子里高亮出来，不放进写作提示【核实】。最有用：**按"提及"注入设定；套话清单只给检查用。** https://docs.novelcrafter.com/en/articles/8675715-crafting-beats ，https://www.novelcrafter.com/help/faq/ai-and-prompting/codex-context-in-prompting ，https://www.novelcrafter.com/help/faq/ai-and-prompting/ai-isms

**彩云小梦**：续写一次给 3 条走向供挑选，可以回溯分支；没找到官方公开的方法论，以上来自测评文章，未核实。最有用：**多候选再挑。** https://www.sanwenge.com/post/1136.html

**马良写作（中文网文 AI）**：统计了 5.7 万个热门书章尾：56% 停在事件还在进行时，31% 最后一句是台词；AI 写的章尾爱"下结论、表决心、说破下一步"。对照实验：给写手禁用清单加坏例子，违规反而升到 33%；改成三句正面要求后违规降到 0%。另外，大模型给"钩子强度"打的分不可信，同一章对比时它 12 次判旧写手更好，判真人更好的只有 2 次【厂商自报】。最有用：**禁令留给审稿，写手只拿正面要求。** https://maliangwriter.com/blog/novel-chapter-end-hooks-techniques

## 二、GitHub 开源

**inkos（★11.3k）**：流程是 Planner 产出本章意图（必须保留什么、必须避免什么）→ Composer 选上下文 → Writer 写 → Settler 把有正文证据的状态增量写回 → 审稿出"带证据的观察"，不卡正文的完成状态，修订另起动作。"读者契约"参考文件要求：手机第一屏要有异常或风险，第 2 章让金手指可见地用一次并产生后果，第 3 章用行动亮出短期目标；每章至少改变一条主轴加一条辅轴；钩子不能靠"提到"来维持，必须有人行动、付代价或改变认知【核实】。最有用：**章节意图加推进轴两个字段。** https://github.com/Narcooo/inkos ，https://github.com/Narcooo/inkos/blob/master/packages/core/skills/inkos-long-writing/references/reader-contract-and-progression.md

**AI_NovelGenerator（★6.5k，旧版提示词在 old 分支）**：章节蓝图规定每 3–5 章一个悬念单元、"紧 2 章松 1 章"，每章写明悬念类型、伏笔操作（埋/强化/回收）、颠覆强度 1–5 星；维护角色状态文档【核实】。正文提示要求"非常规感官组合，如'听见阳光的重量'"，我认为这正是装腔文风的来源之一【推断】。https://github.com/YILING0013/AI_NovelGenerator/blob/old/prompt_definitions.py

**chinese-novelist-skill（★5.0k）**：每本书有一份文风基准（文风指纹、基准段落、AI 味负面清单）；13 种章末钩子；每章按 写前分析→撰写→润色→字数检查 走，不合格最多修 3 轮【核实】。最有用：**每本书有一份"基准段落"。** https://github.com/PenglongHuang/chinese-novelist-skill

**ainovel-cli（★2.3k）**：用"指南针"（终局方向）做滚动规划，开局只细化第一个弧；有成长、竞技、探索、恩怨、日常五种弧型节奏模板；Editor 按 7 个维度评审（含钩子和审美），监控"合同履约率"；写当前章时加载下一章大纲，用来设计章末钩子【核实】。https://github.com/voocel/ainovel-cli

**NovelForge（★1.3k）/ Long-Novel-GPT（★1.3k）**：前者按 Schema 约束卡片生成，用 @ 语法引用上下文；后者自上而下扩写，文风提示是"天蚕土豆常用词表"，按词表模仿很容易出套话【核实；后半句为推断】。

## 三、论文（均打开 arXiv 摘要页核实）

- **Re3**：先做计划，写的时候反复注入计划和当前状态；每步生成多个续写，按情节连贯和贴题程度重排挑选，再编辑修正事实一致性。连贯性 +14%，贴题 +20%。https://arxiv.org/abs/2210.06774
- **DOC**：把创意负担前移到更细的分层大纲，写作时再用控制器保证正文贴着大纲走；相比 Re3，有趣度 +20.7%。https://arxiv.org/abs/2212.10077
- **Agents' Room（DeepMind）**：规划代理（冲突、人物、设定、情节）写进共享草稿板，写作代理按 铺垫/上升/高潮/回落/结局 分段写；评测用成对偏好比较（情节、创意、发展、语言），9900 组人工比较；还发现机器文本句式更模板化、更重复。https://arxiv.org/abs/2410.02603
- **Dramatron**：一句话梗概→人物→节拍→地点→对白，逐层串联提示。https://arxiv.org/abs/2209.14958
- **DOME**：大纲随写作动态调整；用时序知识图谱做记忆，并用它自动检查前后冲突。https://arxiv.org/abs/2412.13575
- **StoryWriter**：先列事件和事件关系，再安排每章写哪些事件、怎么交织，写作时按当前事件压缩历史。https://arxiv.org/abs/2506.16445
- **Weaver / LongWriter**：前者是专用写作模型，按职业作者的偏好对齐；后者的 AgentWrite 先分段规划再逐段写。https://arxiv.org/abs/2401.17268 ，https://arxiv.org/abs/2408.07055

## 四、网文方法论

- **猫腻访谈**：节奏是"小高潮、平复期、余韵"，几个小高潮后要有大高潮，"挖扣子—填坑"做两三层就够；"自己赢"不是快感来源，"看对方怎么输"才是；主角要有安全感，再在上面叠一层可控的不安全感【核实】。https://www.thepaper.cn/newsDetail_forward_30394339
- **爽点三拍**：期待→压抑（压的过程要可见、有代价）→释放；只有第三拍不叫爽点，叫通知【核实】。https://www.socratopia.app/library/webnovel-writing-zh/chapter-2
- **黄金三章**：认识主角、产生共情、期待后续；第 1 章给困境，第 2 章兑现卖点，第 3 章扩大危机。和 inkos 的读者契约互相印证【核实】。https://www.xs91.com/archives/6138.html
- AI 工具里真正把这些方法结构化的：inkos（读者契约）、AI_NovelGenerator（蓝图字段）、马良（章尾检查）。

## 五、NovelOS 应借鉴的 10 条改造（按对"读者想不想看"的影响排序）

1. **立项→加"读者契约"卡**：主角要什么（看得见的短期目标和长线目标）、本书反复交付哪一种爽、金手指第一次怎么可见地用。卷纲必须写出 承诺→危机至少递增 3 次→兑现→新钩子。（inkos、猫腻）
2. **章纲从"排事件"改成"读者账本"**：每章必填 主角本章目标 / 阻力 / 转折 / 结果；正在压哪条期待线，处在三拍的哪一拍；爽点写清谁输、怎么输、谁看见、主角拿到什么；推进轴（主+辅）；最后一拍（具体到哪句台词、什么消息、谁出现）；伏笔用 ID 操作。缺字段就不放进写作。（DOC、inkos、AI_NovelGenerator、马良）
3. **写手提示改成正面要求**：禁令、套话词表、坏例子全部移到审稿和 lint；写手只拿 场景卡 + 正面要求 + 文风样例。删掉"非常规感官""隐喻系统"这类文学化指令。【依据为厂商自报数据，属推断，建议自己做 A/B 验证】
4. **卷纲层由程序排节奏**：3–5 章一个单元，每单元一个中爽点，紧 2 松 1，连续平路不超过 2 章；落笔前用代码检查爽点间隔和颠覆强度分布。（AI_NovelGenerator、ainovel 弧型模板、猫腻）
5. **文风用样例，人物写"四件事"**：每本书放一段 300–1000 字的基准段落，取自拆书或用户自选；人物卡加上 想要 / 知道 / 害怕 / 付得起什么，再加口癖和说话方式样例，治"没有活人味"。（Sudowrite、chinese-novelist、inkos）
6. **审稿分硬门和软反馈，不再强行放行**：连续性、字数、格式是硬门；吸引力问题生成具体修订目标，在出问题的最小一层修（章纲弱就重写章纲，不去重写正文）。自愈 N 次仍低分的标"待处理"，一键成书模式下停在决策点。（inkos、ainovel）
7. **关键处多候选，两两比较选优**：开篇、本章爽点场景、章尾各生成 2–3 版，两两问"哪版更让人想点下一章"，代替绝对打分。（Re3、Agents' Room、彩云）【推断：成对比较比绝对打分可靠，佐证是马良的自报数据和 NovelOS 自己"分数挤在一个区间"的经历】
8. **审稿时模拟番茄读者**：每章强制回答三个问题：主角这章想要什么？我在等什么？最后一句之后我想知道什么？答不上来就判不合格。【推断】
9. **伏笔和期待线建 ID 账本**：状态分 open / progressing / resolved，规划只能引用已有 ID；超过 N 章没推进的标"停滞"。（inkos、ainovel）
10. **滚动规划细到弧**：只细化当前弧，弧末复盘时读入读者账本再展开下一弧。NovelOS v0.16.0 已有卷末复盘，可以把粒度降到弧。（ainovel、DOME）
