# 写作提示词与方法调研（v0.6，2026-11-13）

起因：NovelOS 生成的第 1 章样章（番茄向都市高武「开局武馆快关门，结局弟子全成神」，卖点“教徒即涨修为”，
原文见 `backend/tests/fixtures/ch1_sample_2026-11-13.txt`）经人工审稿发现四类问题：连续性/物理逻辑、语义写反、
开篇结构与卖点缺席、语言口癖。本文先给出管线根因（以 v0.5.1 代码为准），再列出调研来源与借鉴点，最后说明 v0.6 的改法。

所有来源均为本次实际打开过的页面；“搜索摘录”表示只看到了搜索结果摘录，未能完整打开正文。
协议处理：MIT / Apache-2.0 / CC BY 可改写引用并在 `THIRD_PARTY_NOTICES.md` 署名；GPL / AGPL / 无协议 / 文章只借思路，不复制原文。

---

## 一、根因清单（v0.5.1 代码）

| 样章问题 | 根因 | 代码位置（v0.5.1） |
|---|---|---|
| 合同从反派手里跳到柜台、硬壳变厚纸；皮鞋变金属脚掌；钝角变九十度；义体臂发紫；已面朝门外又“转过身来迎着门外”；车开走灯还照进正堂 | 正文逐场景独立生成，下一个场景只拿到上一场景**末尾 200 字**（`prev_tail = texts[-1][-200:]`），看不到前面写过的道具外观、衣着、角度；没有任何“站位/朝向/手持物/服装/身体”的场景级账本，模型只能凭细纲重新想象现场 | `services/writing.py::_write_variant`；`prompts/writing_scene.md`（只有 `$previous_tail`） |
| 同上（跨章） | 章与章之间只有事实底账（位置/伤势等粗粒度键）与上一章结尾 300 字，没有场景物理状态 | `services/context.py::build_context_pack`（`chapter_tail`、`state_block`） |
| 审稿没抓到上述矛盾 | 审稿维度只有 hook/pacing/payoff/character/coherence 五个，coherence 只对照“底账与上一章结尾”，不要求章内逐物核对；提示词没要求引用前后两句 | `services/review.py::DIMENSIONS`；`prompts/review.md` |
| “没有上限”的红标写反（本意是到顶） | 写作提示词与审稿都没有“语义正确”检查项；没有任何“贬褒/否定写反”的自查要求 | `prompts/writing_scene.md`；`prompts/review.md` |
| 少年叫“师父”、主角说“入门教你的”，又是来“补录”的被清退者 | 细纲与场景节拍没有“人物关系/称呼依据”字段；新人物不在设定库时只在写前核对里提示“交代身份”，没有关系与称呼约束 | `prompts/scene_plan.md`（无 relations）；`services/context.py::preflight_check` |
| 前三段全是氛围，第四段才有冲突 | 规则只有“主角 300 字内出场、1000 字内出现钩子”，没有“前三行见冲突”；细纲没有 opening_hook 字段，场景节拍第一拍也不强制从冲突起 | `rules/writing.md` 一、番茄开篇硬指标；`services/context.py::GOLDEN_TASKS[1]` |
| 卖点金手指（收徒涨修为）在少年交补录表时没触发，本章完全没体现 | 黄金三章规则把“金手指首次使用”放在第 2 章（outline.md 第 7 条、GOLDEN_TASKS[2]），第 1 章没有任何“卖点露面”要求；细纲 schema 没有 cheat_beat；场景拆分看不到金手指卡（scene_plan 只拿到章细纲文本） | `rules/outline.md` 第 7 条；`services/context.py::GOLDEN_TASKS`；`services/outline.py::CHAPTER_SCHEMA`；`services/writing.py` 场景拆分 |
| 主角全程无内心，代入感弱 | 规则反复强调“心理要有外部依据、不写长独白”，却没有“每场至少一处简短内心”的正向要求，模型就干脆一句不写 | `rules/writing.md` 二.3、一.4 |
| 群众反应镜头切约六次 | “打脸四拍”第 4 拍就是“围观的反应”，且每个场景独立生成，每场都把围观反应写一遍；没有全章上限，也没有跨场景计数 | `rules/writing.md` 一.5；`services/writing.py::_write_variant` |
| 结尾钩子堆三个 | 每个场景节拍都有 exit_hook，末场景又承接细纲 hook_end，再加上细纲伏笔“埋下”动作，最后一场同时收到三个“悬念”指令 | `prompts/scene_plan.md`；`services/writing.py::normalize_scenes` |
| 反派口头禅“嘛”4 次、“对吧”3 次 | 人物卡口头禅原样注入每个场景的上下文（`口头禅：X、Y`），没有频次限制提示；规则虽写“全章不超过 1–2 次”，但每个场景独立生成、互相看不到已用次数，于是每场都用 | `services/context.py`（说话方式那一行）；`rules/writing.md` 三.3 |
| 死死 5、硬生生 3、一把 3 | lint 只查 AI 腔词表与弱化副词（缓缓/微微/轻轻…）密度，不查“死死/硬生生/一把/狠狠”这类强化词的章内重复；也没有逐场景的已用额度 | `lint/humanlint.py::weak_adverb_density`；`lint/banned_zh.py::WEAK_ADVERBS` |
| 空气像灌了铅、像砂纸在磨、背脊像生铁条 | 陈腐比喻表只有 5 条字面量（像一潭死水、受惊的小兽…），没覆盖网文高频万能比喻 | `lint/banned_zh.py::_LITERALS["陈腐比喻"]` |
| 量词错误“一柄铁砣” | 无任何量词搭配检查 | — |
| lint 发现了也修不准 | 定点修整只把“词 + 次数”交给模型（`AI 腔：XX（N 处）`），没有原句，模型只能自己找 | `services/writing.py::patch_rewrite` |

---

## 二、调研来源与借鉴点

| # | 来源 | 发布/更新时间 | 协议 | 借鉴点 | 为什么适用 |
|---|---|---|---|---|---|
| 1 | Anthropic《Prompting best practices》<https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices> | 页面覆盖 Claude 4.x–5.x，2026 在线版 | 文档 | ①说清“要做什么”而不是只说“不要做什么”；②给指令附上原因，模型能泛化；③用相关、多样的正反例并用标签隔开；④长输入放前、指令放后；⑤用结构化格式（JSON）记录状态；⑥自我校对：“完成前按标准检查一遍” | 旧规则大量“禁止…”而缺正向要求（例如只禁长独白，结果主角一句内心都没有）。v0.6 每条硬规则都配正例/反例与原因；场景提示词用 `<chapter_so_far>`、`<scene>` 标签分隔输入，指令放在后面；写完三项自查 |
| 2 | r/WritingWithAI《The reason your AI fiction feels flat…》<https://www.reddit.com/r/WritingWithAI/comments/1uemevj/> | 约 2026-07（帖子显示“4mo ago”） | 社区帖 | ①内容与文风分开处理，编辑轮是“删口癖”；②长弧里人物会退化成同一个“流畅叙述者”，要有逐人物锚点；③**把未解决的线索当作显式状态逐场传下去**，否则模型会提前收束；④用“可操作的廉价指标”而不是一个不透明分数 | 直接对应“逐场景独立生成”这个根因：v0.6 的场景状态账本 + 剩余额度就是“显式状态逐场传递”；lint 指标都指向可修的具体句子 |
| 3 | zenstory-ai / worldwonderer **oh-story-claudecode**，story-deslop `banned-words.md` <https://raw.githubusercontent.com/worldwonderer/oh-story-claudecode/main/skills/story-deslop/references/banned-words.md> | 仓库 2026-04 创建，持续更新 | MIT | 把“猛地、死死地、瞬间”等列为**语境敏感词**：单章偶发不判错，“连刷扎堆”才改；“替换不复用”；模板比喻表 | 正好是样章“死死×5”的情况。v0.6 不做“出现即错”，而是按章内频次 + 字数放宽阈值，只点名超出额度的那几处 |
| 4 | evelynyaxueke **anti-ai-writing-kit-zh** <https://github.com/evelynyaxueke/anti-ai-writing-kit-zh> | 2026（报告日期 2026-07-20） | MIT（Copyright 2026 Evelyn Ke） | “正向默认值告诉智能体应该怎样写，不只列禁词”；“机械扫描通过后仍需人工语义检查”；从起稿就加载规则 | 支持 v0.6 的“起稿时注入额度 + 写后 lint 点名 + 审稿语义检查”三层结构；只借思路 |
| 5 | **番茄小说网作家课堂**《如何稳定剧情，让读者追更不停？》<https://fanqienovel.com/writer/zone/article/7605818896267870270> | 2026-02-21 | 平台文章 | 目录：首页见山、章末留钩、金手指的创新性与**对情节的推动**（正文为动态渲染，仅打开到目录；“第一页比前三章更重要”来自搜索摘录） | 官方口径：第一页就要进入事件；金手指要推动情节而不是摆设 → 第 1 章“前三行见冲突 + 卖点露苗头” |
| 6 | 网文666《网文开篇黄金三章怎么写，8大平台节奏差异》<https://www.wangwen666.com/post/204.html> | 2026-06-04 | 文章 | 番茄：首章 1500–2000 字，铺垫容忍前 300 字，**冲突 ≤500 字，金手指亮相 ≤1000 字**；新手五坑之一“金手指拖到后面”“主角太窝囊，开篇要有反击苗头” | 量化了番茄的开篇时限，v0.6 把“金手指首用在第 2 章”改为“第 1 章至少露苗头” |
| 7 | 马良写作《网文黄金三章怎么检查？》<https://maliangwriter.com/blog/golden-three-chapters-check-guide> | 2026-08-01 | 文章 | 入局 / 加压 / 承诺；钩子“不一定更炸，但更接近主线” | 已在 v0.2 采用，v0.6 保留并把卖点露面并入“入局” |
| 8 | 句点速写《黄金三章怎么写》<https://jdsx.mkzhuofan.cn/tips/golden-chapters>（搜索摘录） | 2026 | 文章 | 番茄冲突 ≤500 字、金手指 ≤1000 字（与 #6 一致） | 交叉印证 #6 |
| 9 | Narcooo **inkos** <https://github.com/Narcooo/inkos>（搜索摘录） | 2026-03 创建 | AGPL-3.0 | 连续性审查含“角色记忆、**物资连续性**、伏笔回收……”；观察器抽取物理状态事实 | 只借思路：审稿新增 continuity 维度、场景账本记录道具与身体状态；不复制任何代码与文本 |
| 10 | fuxiangxu **novel-ops** <https://github.com/fuxiangxu/novel-ops>（搜索摘录） | 2026 | MIT | `character-state.md` 逐章追踪角色情绪/**位置**/关系/已知信息；角色语言指纹逐章对齐 | 把“逐章”下沉到“逐场景”，并把语言指纹落成可计数的口头禅额度 |
| 11 | tance-mang **chinese-webnovel-skills** <https://github.com/tance-mang/chinese-webnovel-skills> | v0.29（2026） | MIT | `continuity-check.md`：七条逻辑链（行为/因果/资源/身份/伤势/战力/情绪）；`ai-detector.md`：比喻密度、连续同句式、情绪词重复等 12 项量化 | 审稿 continuity 维度的检查清单与 lint“比喻/重复”量化思路；仅思路，词条自写 |
| 12 | lingfengQAQ **webnovel-writer** <https://github.com/lingfengQAQ/webnovel-writer> | 2026-10-06 更新 | GPL-3.0 | Context Agent 写前组装任务书、Data Agent 写后抽状态回写的读写闭环 | 与 v0.6“场景写后吐状态 → 程序合并 → 下一场注入”同构；只借思路 |

未采用：知乎/公众号上的“万能开篇模板”“爆款句式库”类文章，多数无协议、内容同质，且鼓励堆模板，与“去套路”目标冲突；
豆瓣小组帖（2026-03-02）建议“第一章尽量不要有主角心理活动”，与番茄向“代入感”诉求相反，本项目按番茄口径取“每场一处简短内心”。

---

## 三、v0.6 的改法（每条都能在 mock 下跑通并有测试）

1. **场景状态账本**（`services/scene_state.py`，新）：每个场景写完输出 `---STATE---` JSON（人物位置/朝向/手持物/穿着/身体，道具位置/状态，环境），
   程序规范化、合并、渲染后注入下一场；上一章的结束账本存进 `Chapter.changes.end_state`，下一章第一场接着用；
   程序比对前后账本，道具换了位置但正文没写到它 → “道具凭空移动”警告。下一场同时拿到**本章已写全文**（≤6000 字），不再只有 200 字尾巴。
2. **剩余额度**：每个场景前按已写内容计算“口头禅已用几次、群众镜头已用几个、哪些强化词已用够”，写进提示词。
3. **开篇硬约束**：细纲新增 `opening_hook`（1–3 章）与 `cheat_beat`（第 1 章），模型漏写时由程序从冲突与金手指卡补齐（`outline.py::ensure_opening_beats`）；
   场景拆分强制第一场从冲突起、cheat 落到兑现场景、末场只留主钩（`writing.py::enforce_scene_rules`）；场景提示词加“前三行见冲突 / 卖点露出 / 每场一处简短内心 / 章末 1 主钩 + ≤1 副钩”。
4. **lint 新增**（`lint/craft_zh.py` 词表 + `lint/humanlint.py`）：重复强化词（按每千字 0.6 次、至少 2 次放宽）、陈词比喻、量词搭配错误表、群众反应镜头计数（≤3）、
   对白句末口癖（嘛/对吧/是吧/呗…）、人物卡口头禅频次；全部整理成**带原句的 fix_targets**，人味修整逐句定点修。
5. **审稿新增维度** continuity（连续性与物理逻辑）与 semantics（语义正确），要求 comment 写“前文「…」，此处「…」”；程序另加量词错误与第 1 章卖点缺席两项确定性检查；分数仍由程序算。
6. **规则与提示词重写**：writing / chapter_plan / review / humanize 规则包各加一节 v0.6 硬规则（短句、正反例、给原因），
   writing_scene / scene_plan / review / humanize / outline 提示词按 Anthropic 指南改为“输入在前、指令在后、标签分隔、写完自查”。

## 四、已知局限

- 群众镜头、强化词、口癖都是启发式计数，阈值来自一篇样章，未在大语料上校准；会有少量误报（例如“生生世世”被算进“硬生生”族）。
- 状态账本依赖模型如实填写；模型不填或乱填时只能沿用上一场账本并记警告，不能代替审稿。
- “道具凭空移动”只比较道具名是否出现在本场正文里，换个叫法（“那叠纸”）会漏报或误报。
- 第 1 章卖点检查用金手指卡名与 `keywords` 做字符串匹配，卡名不出现在正文里时会误报（只记 mid，不阻断提交）。
