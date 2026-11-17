# 更新日志

## v0.12.0（2026-11-17，设定/大纲锁定与单卡版本 + 生成档案与成本 + 导入已有作品）

### 锁定与单卡版本
- 设定卡、大纲节点新增「锁定」（`Card.locked`、`OutlineNode.locked`，自动迁移）。锁定后任何 AI 都改不了：AI 生成设定（三种模式）、同步作品信息、Agent 改设定/大纲、字段级 AI、灵魂五维、整张/单项 AI 改、AI 重写节点、章细纲展开、完本卷纲调整、伏笔挂章纲都会跳过或拒绝（409）；整体重新生成大纲时有锁定节点会先拦下。作者手动编辑不受限。
- AI 改设定的预览里，锁定卡不出现在改写/删除候选中，结果带 `skipped_locked`；锁定内容会作为「不能改」的约束喂给模型。
- 单卡版本：`Card.versions`（最多 20 版）。手动保存、采纳 AI、AI 批量改、重新生成之前都会存一版；`GET /api/cards/{id}/versions`、`POST /api/cards/{id}/versions/{n}/restore`（回滚前也存一版）。整库快照照旧保留。
- 前端：设定卡片角上锁定开关，编辑抽屉里「锁定 / 版本」，版本抽屉可展开看内容、一键回滚；锁定后隐藏所有 AI 入口。大纲节点编辑里「锁定」，锁定节点在大纲树上带锁标。

### 生成档案与成本
- 新表 `generation`：每次模型调用（对话、Agent、生图，含演示模式）一条，成功 / 空结果 / 失败都记，失败带原因；输出全文保留，记录输入输出 token、耗时、人民币花费、目标字数与实际字数（实际低于目标 70% 标「字数不足」）。
- 追问不覆盖：`POST /api/generations/{id}/followup` 出一条新记录（`parent_id` 指向原条），原结果保留，可在版本间切换。
- 接口：`GET /api/generations`（按作品、类型、状态、收藏、关键词筛选，分页，返回筛选内花费）、`GET/PATCH/DELETE /api/generations/{id}`。
- 模型单价：渠道新增 `prices: {模型: {in, out, image}}`（元/百万输入 token、元/百万输出 token、元/张），在渠道编辑里逐个模型填写；成本预估新增 `cost_cny_est`、`priced`、`budget`。
- 预算：`GET/PUT /api/settings/budget`（每日上限、单本书上限，0 为不限，「今天」按北京时间算）。超出后真实模型调用前直接拦下并说明已用多少、上限多少；演示模式不计费。
- 前端：侧栏「生成档案」页（筛选、搜索、查看结果与要求、复制、收藏、删除、追问出新版本）；设置页「花费与预算」；成本预估浮层显示预计花费和今日已用。

### 导入已有作品
- `POST /api/books/import`：上传 TXT / MD / DOCX（DOCX 不加依赖，直接读文档 XML）或粘贴正文 → 预览：书名猜测、卷（识别「第X卷/部/集」并从正文去掉卷名行）、每章字数、疑点（空章、过短、过长可能漏切、开头重复、章号跳号）。预览在内存里保留 30 分钟。
- `POST /api/books/import/commit`：按预览建书，可跳过指定章；正文入库、章节直接为已提交状态，章字数取中位数。
- 接管：`POST /api/books/{id}/adopt`（任务 `book_adopt`，可选 steps：summary / bible / ledger / outline）：逐章补摘要（已有摘要的章跳过，中断后重跑接着做）→ 从摘要反推设定卡、事实账本、伏笔账本（新提示词 `adopt_bible`；同名卡不覆盖，写前存快照）→ 按卷生成卷 / 弧 / 章大纲节点并挂上章节。`GET /api/books/{id}/adopt` 看接管进度。
- 前端：「我的书」页「导入作品」：文件 / 粘贴 → 预览勾选章节 → 导入，默认导入后自动接管。

## v0.11.1（2026-11-17，同人联网取材 + 热门题材模板 + 选书网格修复）

### 同人：联网取材
- 原著资料新增来源 `source="search"`：只填作品名（必填）+ 可选重点人物/剧情范围（focus）+ 深度，后台任务用「任务路由 → 联网搜索」模型分多轮检索（quick 2 / standard 4 / deep 6+ 轮，focus 每项各加一轮，最多 6 项）：作品概况与世界观/力量体系等级、主要人物（性格、说话方式、关系、能力与上限）、关键时间线与名场面、势力与地点、体系细节、后续剧情与结局、配角与反派；结果交给原著设定卡提炼（新提示词 `fanfic_source_web`，注明材料来自联网检索、可能有误、不确定的不写）再合并。
- 原文 + 联网结合：paste / txt 新增 `web_supplement`（前端在配置了搜索模型时默认勾选），提炼原文后联网补齐原文没覆盖的人物、设定和后续剧情；合并以原文提炼为准，定位/关系/势力立场冲突项以原文为准并写进 warnings，联网新增的角色在备注里标「联网补充」。
- 已有原著资料可「联网补充」：`POST /api/fanfic/sources/{id}/supplement`（任务 `fanfic_supplement`），以现有设定卡为准只补空缺。
- 没有配置联网搜索模型时，联网取材 / 联网补充返回 422 并提示去「设置 → 任务路由 → 联网搜索」配置；mock 模式返回演示资料。
- 纯联网资料没有原文指纹：原著重合检查返回 `no_fingerprint: true` 和说明，不报错。
- `fanfic_source` 新列 `refs`（来源链接）、`template_id`、`web_rounds`（自动迁移）；`LLMGateway.search()` 新增可选 `system`（≤1500 字）参数。

### 同人：热门题材模板
- `GET /api/fanfic/templates`：18 个内置热门同人题材（斗罗大陆、斗破苍穹、漫威、龙族、宝可梦、火影忍者、海贼王、哈利·波特、原神、崩坏：星穹铁道、凡人修仙传、诡秘之主、名侦探柯南、遮天、完美世界、DC、一人之下、咒术回战），每个含作品名、别名、类别、一句话简介、主要人物名、检索重点、常见同人写法（附对应方向）和推荐方向；同时返回当前联网搜索状态（web / mock / none）。只含事实性元数据，不含原著文本。
- 前端同人页新增「联网取材」模式：可搜索、按类别筛选的模板卡，点模板自动填作品名和重点人物；也能手填任意作品名。来源标签显示「联网」/「粘贴+联网」，详情页显示来源链接与「联网补充」按钮。
- 建同人书：来源资料带模板时展示该题材常见写法（可多选，写进「作者补充」，并标出推荐方向）。

### 修复
- 选书框（选题向导 / 拆书页）在窄容器里卡片被挤成一字一行：网格改为按容器宽度自适应（`auto-fill, minmax(min(100%,280px),1fr)`），分类标签不换行；拆书历史、熔炉参考书、选题结果、同人方向卡、同人设定卡编辑同样改为自适应网格。

## v0.11.0（2026-11-17，完本模式 + 整书体检 + 短剧分镜档）

### 完本模式（每本书可选，默认仍是连载，旧功能全部保留）
- 设置 `GET/PUT /api/books/{id}/wanben`：字数目标 15/20/30 万预设或自定义、每章字数、每批章数、精修范围（前 N 章 / 全书 / 自选区间 / 不精修）、精修待审批时暂停、自动连续。
- 卷纲倒推 `POST /api/books/{id}/wanben/plan`（任务）：按目标字数算总章数，补全卷纲（章号区间、危机、高潮章、收束），末卷安排完整结局；已有大纲只补缺并返回差异。
- 分批连写 `POST /wanben/batch`（任务，可暂停、断点续跑）：每批补细纲→写→审→修→提交，批末出抽检报告（字数、开头冲突、高潮、章末钩子、人名/数字/战力一致性、读者分）。精修范围内的章只写不提交，等你审批。
- 章节迭代 `POST /wanben/iterate`（任务）：任意已写章按要求定点修或整章重写，1–5 轮，每轮出新版本与分数变化，可对比、采纳、弃用、撤回；不设自动终止。
- 进度 `GET /wanben/progress`；整书 TXT `GET /wanben/export.txt`。
- 新表 `wanben_batch`、`wanben_iteration`，`book.mode`、`book.wanben` 新列（自动迁移）。

### 质检
- 整书体检 `POST/GET /api/books/{id}/book-check`：规则层（字数档位参考、短章、重复/近似章、水化、数值、伏笔未回收、章号标题断档、结局收束）+ 模型层（人物状态、战力、势力、时间线、主线跑偏、结局仓促），给结论、分数、问题清单与一键修。
- 可改编度 `POST /api/books/{id}/adaptability`：人设、冲突密度、反转、可拍性、对白、每章可切集数六维。
- 同质化自查 `POST /api/books|ideas/{id}/homogeneity`：与榜单前列书比对。
- 短剧分镜风格档 `duanju`（沿用番茄档 lint 阈值）与章节「短剧自查」`POST /api/chapters/{id}/duanju-check`；`GET /api/platform-styles`。

### 其它
- 发布包默认不再附 AI 申报提示，包装规则去掉申报句；发布包增加整书 TXT。
- 拆书粘贴正文后可直接开始；移动端按钮可点高度 ≥36px；已有原创书可在概览/编辑信息里「设为同人」。

## v0.10.0（2026-11-17，合并 v0.9.3 拆书工作台与引导、v0.9.4 提交前定点修与数值一致性、v0.10 同人创作）

### 同人创作
- 原著资料：`POST /api/fanfic/sources`（粘贴或 TXT 上传，≤30MB，任务）从作者导入的原著提炼「原著设定卡」——角色（性格/说话方式/口癖/关系/能力与边界）、世界观、势力、关键事件时间线、名场面（用自己的话）。长文本按重点段落→开头→均匀抽样取 20 万字，quick/standard/deep 分 1/2/4 轮提炼并合并。**原文不入库**，只存设定卡与 8 字指纹；除口癖外与原文连续 8 字相同的字段清掉并提示。`GET/PUT/DELETE /api/fanfic/sources/{id}`、列表；设定卡可手改。
- 版权确认：建同人书必须提交 `copyright_ack: true`（仅供个人创作学习、发布需遵守平台同人规则与原著授权），否则 400；书上记确认时间。
- 同人书：建书时带 `fanfic: {source_id, fidelity, direction}`，或 `POST/PATCH/DELETE /api/books/{id}/fanfic`；Book 新字段 `fanfic`。遵循度三档 strict / moderate / loose，原著卡摘要与遵循规则自动进大纲、写章等所有书设定上下文；`import-cards` 可把原著角色/势力/世界观写进设定库。
- 12 种方向模板 `GET /api/fanfic/directions`：原著向补完、if 线改写、穿书、重生、系统、AU 现代、AU 古代、配角主视角、CP 向、反派洗白、后日谈、跨作品联动（说明、写作要点、风险、建议遵循度、想法模板）。
- OOC 检查 `POST /api/chapters/{id}/ooc-check`（任务）：对照原著角色卡逐角色打分、列出言行/口癖/关系/能力越界/时间线问题（带本章原句），按遵循度调宽严，结果存章节 `fanfic_meta`；`GET /api/chapters/{id}/ooc`。
- 原著重合检查 `POST /api/chapters/{id}/fanfic-overlap`：与原著的 8 字 n-gram 重合计数、最长片段、占比与告警等级（复用拆书指纹，口癖与人名不计）。
- 新表 `fanfic_source`；`book.fanfic`、`chapter.fanfic_meta` 新列（自动迁移）。

## v0.9.4（2026-11-17，随 v0.10.0 一同发布）

### 写作流程
- 提交前修中等问题：章节提交（自动提交与 `POST /chapters/{id}/commit` 都走）前，若最后一轮审稿（含番茄老读者审读）里有 continuity / retention 类 **mid** 问题，先按对应审稿补丁逐字替换，没有补丁的按问题描述再定点改一次，然后提交。每章只做一次，旧正文进历史可撤回；记录在 `review.pre_commit_fix`。审批模式为「逐条审阅」时跳过。开关 `fix_mid_before_commit`（全局默认开，可按书覆盖）。
- 审稿补丁后自动重审：写章流程自动应用补丁后再审一次（最多 1 次），新审稿写回章节（旧补丁保留在列表前面，过期的标 `stale`）；high 仍在则不提交、`review.flagged=true` 并写进变更警告。开关 `auto_rereview`（默认开，可按书覆盖）。
- 书级开关：`GET/PUT /api/books/{id}/writing-settings`；全局 `PUT /api/settings/writing` 新增两个字段。

### 数值一致性 lint
- 新规则 `app/lint/numeric_zh.py`（纯规则）：同章前后、或与设定卡/事实账本对照，同一对象的重量（斤/公斤/千克/吨）、身高长度（米/厘米/丈/尺，“一米八”）、年龄、期限（三天后/后天）、境界（炼气三层…）、机甲参数（高/重/功率/时速）不一致 → mid / continuity 问题，带位置（offset、段落、原句、对照来源）；市制与公制混用也提示。结果进 lint（`numeric_conflicts`）和审稿 `review.issues`（`source: "lint:numeric"`）。

### 任务断点续跑
- 写章任务每完成一步（拆场景、每个场景、每个版本、建章、采纳、精修、补丁重审）写断点（新表 `job_checkpoint`）。服务重启时有断点的写章任务标 `interrupted`（其余仍 failed）；`POST /api/jobs/{id}/resume` 用同一个任务从最后完成的场景继续；失败（failed）且有断点的任务也能续跑。`GET /api/jobs/{id}` 新增 `resumable`、`checkpoint`。

### lint 阈值校准
- craft_zh、长段、瀑布流短段、弱化副词等阈值集中到 `app/config.py` 的 `lint_profiles`（番茄档 / 出版档两套，按平台风格档选用，可用 `NOVELOS_LINT_PROFILES` 覆盖）。
- 按 7 章样章校准：番茄档长段 70→100 字，且要 ≥3 段、占比 ≥10% 才算问题，定点修最多点名 3 段；样章「需定点修」从 7/7 降到 2/7。统计见 `docs/research/lint-calibration-v094.md`，脚本 `backend/scripts/lint_calibration.py`。
- lint 输出新增 `lint_tier`、`numeric_conflicts`。

## v0.9.3（2026-11-17，随 v0.10.0 一同发布）

### 作品完整度与新手引导
- `GET /api/books/{id}/completeness`：10 项待办（概览、世界观、主角五维、配角、势力地点、大纲、前三章章纲、第 1 章、书名简介、封面），0–100 分，每项带跳转或一键任务。
- `GET/PUT /api/onboarding`：四步引导（接模型→立项→设定与大纲→第一章），按库内数据自动打勾，可手动勾选与关闭。

### 设定库
- 字段级 AI：`POST /books/{id}/bible/{entry}/field-ai`（补全/改写/扩写，任务只返回对比稿），`.../field-ai/apply` 采纳写库（写前存快照）。
- 「用于 @引用」：条目 `ref_enabled`；`GET /books/{id}/refs?q=`；写章、场景计划、改写、大纲、Agent 的指令里 `@条目名` 自动注入该条目全文。
- 角色灵魂五维 `soul`（欲望/恐惧/伤口/信念/声音），按键合并；`POST /books/{id}/characters/{entry}/soul` 一键补全（fill 模式保留已有项）；写章时出场角色带一行五维。
- 弃用条目 `status=deprecated`：不进任何生成上下文，列表默认隐藏（`?include_deprecated=true` 取回），快照与回滚保留。

### 章节与成本
- 书级审批模式 `approval_mode`（auto/review，与 `agent_auto_apply` 双向同步）；显式 review 时写章、人味修整、描写增厚只出对比稿不落库。
- `POST /api/estimate`：调模型前估算 token、调用次数、模型与耗时（耗时按历史平均）；AI 率检测（朱雀）不计 token。
- 新表 `llm_usage` 记录每次模型调用；`GET /books/{id}/usage`、`GET /api/usage?days=`。

### 拆书工作台
- `POST/GET /api/teardowns`、`GET/DELETE /api/teardowns/{id}`：来源可选榜单书、粘贴或 TXT（≤20000 字），产物含结构、人设模板、金手指、卖点、节奏图、可复用套路；原文不入库，只存 8 字指纹与专名表。
- `to-idea` 生成选题，`to-bible` 写入设定（去专名、与原文连续 8 字相同的跳过）。

### 前端
- 完整度环与待办、首页新手引导卡、字段 AI 按钮与对比浮层、@ 补全、五维卡、弃用折叠、章节吸顶工具栏与审批切换、成本提示浮层（可关闭）、本书用量卡、拆书全屏工作台。

## v0.9.2（2026-11-16）

### 风向标日报升级（榜单 → 立项）
- 日报新增 `headline`（≤40 字定调）、`summary`、每个榜的 `risks`、`inspirations`（4–6 张灵感卡：书名、一句话钩子、主角、核心机制、第一章开局、3 个卖点、借的哪个榜）、`opening_hooks`、`plot_devices`、`writing_advice`、`risk_alerts`。旧字段全部保留，旧报告照常可读。
- 灵感卡与榜上书重名的删掉；与榜上书名+完整简介做 8 字 n-gram 比对，过相似的删掉并记 `warnings`。`idea_hooks` 模型没给时由灵感卡派生（title / pitch=logline）。
- 每榜读的样本改为前 N 本，N 由新配置 `radar_report_top_n` 控制（默认 30，原来总榜 12、题材 15）；进提示词的简介截到 80 字。报告 `meta` 记录 `top_n` 与实际读的本数 `books_read`。
- 新 scope：`board:<g>:<read|new>`（只读一个总榜）、`category:<g>:<read|new>:<题材>`（题材的单个榜）；旧写法 `category:<g>:<题材>` 保持阅读榜+新书榜。`GET /api/radar/report/latest` 为 `GET /api/radar/report` 的别名。
- 日报配置 `GET/PUT /api/radar/report/config`：`radar_report_top_n`、`radar_report_auto_scopes`（默认 `["overall"]`）。自动日报开关仍是 `auto_report`，开启后按 auto_scopes 各生成一份；刷新结果新增 `report_job_ids`。

### 立项
- 种子立项 `POST /api/ideas/from-seed`：`expand=false` 不调模型，种子直接存成选题（评分留空）；`expand=true` 走任务，planner 扩成完整选题（同一套 Idea 结构、禁用套路清单与复核打分），并和参考书做来源自检。`Idea.source` 带 `type`（trend_report / rank_book / paste / fusion / manual）与 `ref`；建书时种子里的主角、核心机制并进 premise。
- 一键整理 `POST /api/ideas/organize`（任务）：把作者粘贴的零散想法（≤5000 字）整理成完整选题，不改作者核心设定，记录 `kept_core` / `added` / `conflicts`。
- 多本熔炉 `POST /api/ideas/fusion`（任务）：1–3 本参考（榜单书 / 书名 / 粘贴原文），权重归一化，按权重融合结构、卖点、风格产出原创选题；结果与每本参考的书名、简介、原文做 8 字 n-gram 比对，过相似丢弃计 `dropped`。粘贴原文不入库。

### 仿写立项 TXT
- `POST /api/radar/imitate/extract`（multipart file 或 JSON text，同步、不入库）：识别 utf-8 / gb18030（含 BOM），按「第X章 / 第X回 / Chapter N / 序章」切章，返回书名猜测、前 10 章目录与字数、前 10 章拼接正文（≤20000 字），可直接喂深度拆解与换皮。

### 提示词
- 新增 `prompts/idea_seed.md`、`idea_organize.md`、`idea_fusion.md`；`prompts/trend_report.md` 与 `rules/trend_report.md` 增加灵感卡、开篇钩子、剧情装置与风险提醒的要求。

### 其它
- 版本号 0.9.2。

## v0.9.1（2026-11-16）

### 榜单书架化
- `RankItem` 新增 `cover_url`、`first_chapter_id`、`last_chapter_id`、`last_chapter_title`、`last_update_at`、`chapter_count`（旧库自动补列：空串 / 0 / NULL）。抓榜时从番茄接口的 `thumbUri`、`firstChapterItemId`、`lastChapterItemId`、`lastChapterTitle`、`lastChapterUpdateTime` 填充；`chapter_count` 从最新章标题解析中文/阿拉伯章号（「第八十章」→ 80），0 表示未知。示例数据给出章数、最新章与更新时间示例值（无封面）。
- 列表项新增计算字段 `cover`（本站封面代理相对路径，无封面为 null）、`source_url`（番茄书页）、`first_chapter_url`（阅读页）。
- 封面缓存代理 `GET /api/radar/cover/{book_id_ext}`：`data/covers/{id}.jpg` 有就直接返回（长缓存），否则用最新条目的 `cover_url` 下载（10 秒超时、必须 `image/*`、≤2MB）后存盘；失败 404。实际格式按文件头识别（番茄有时给 PNG）。抓榜后后台预缓存本次快照封面（`NOVELOS_RADAR_CACHE_COVERS`，默认开；间隔为 `radar_interval_s` 的一半且不低于 0.5 秒；失败忽略）。鉴权与其它 `/api` 相同，同源 `<img>` 自动带登录 Cookie。
- 单书详情 `GET /api/radar/books/{id}/detail`：解析番茄书页 `__INITIAL_STATE__.page`（取不到再用正则兜底）得到 `chapter_total`、完整简介、章节目录前 50 与最后 10 章；缓存 24 小时（`data/radar_detail/`，`?refresh=true` 强制重抓）；抓取失败仍返回条目并带 `detail_error`。
- 单书 AI 灵感 `POST /api/radar/books/{id}/ai {kind: title|cover|blurb, n}`（Job，planner 路由）：换皮书名 / 封面提示词（3:4，可直接喂封面生成）/ 简介候选，只学同类爆款思路；结果用 v0.7 的 8 字 n-gram 与原书名、原简介比对，书名候选另查与原书名连续 4 字相同，重合的丢弃并计入 `dropped`。新提示词 `prompts/radar_book_title.md`、`radar_book_cover.md`、`radar_book_blurb.md`，可在 /api/prompts 覆盖。

### 朱雀 AIGC 文本检测（只做检测）
- 接入腾讯 EdgeOne Makers `@makers/zhuque-text`（`POST {base_url}/v1/providers/zhuque-text/classify`）。设置 `GET/PUT /api/settings/zhuque`：密钥 Fernet 加密存库，只回 `zhuque_configured` 与尾号 4 位；`zhuque_base_url` 可改成自己的网关域名；PUT 局部更新。
- 长文按段落切块（每块 ≤8000 字，`NOVELOS_ZHUQUE_CHUNK_CHARS`），逐块调用后按字数加权合并 softmax / ratio / labels_ratio，分段位置换算回全文偏移；30 秒超时；401/403/429 给中文提示；累计 total_tokens。档位：softmax <0.5 低、0.5–0.85 中、≥0.85 高。
- `POST /api/detect/aigc`（Job）检测任意文字；`POST /api/books/{bid}/chapters/{cid}/aigc`（Job）结果存进章节新字段 `aigc`（含 `content_hash`，正文改动后 `stale=true`）。
- 写章流程默认不调用；可选 `zhuque_auto_check`（默认关），开启后章节提交时后台检测一次，失败不影响提交。不会根据检测分自动改写。

### 语感重塑
- `POST /api/books/{bid}/chapters/{cid}/polish-voice`（Job，writer 路由）：按 `prompts/polish_voice.md` 改成老网文写手的口语语感、提升可读性（成语换口语、换掉套路动作、动词先行、长短句交替、按平台控制段长、具体感官细节），情节/数值/人名/对白含义不变。结果走现有改写对比稿流程（`apply-rewrite` 采纳、`undo` 撤回），不直接覆盖正文。
- 程序校验：数字/数值词集合与原文一致、主要人名都在、字数变化在 ±20% 内、番茄档段长 ≤70 字，不符的写进 `warnings`。
- Agent 新工具 `polish_voice`：产出「章节改写」提案。

### 其它
- 版本号 0.9.1。

## v0.9.0（2026-11-16）

### 榜单雷达
- **番茄新书榜**：网页榜单接口同时抓「阅读榜」（`rankMold=2`，30 万字以上，页面 `/rank/{g}_2_{cid}`）和「新书榜」（`rankMold=1`，30 万字以下、未断更，页面 `/rank/{g}_1_{cid}`）。2026-11-16 匿名实测：`/rank/1_1_1141` 页面内嵌数据与 `rankMold=1` 返回一致，两类榜 `rankVersion` 相同。可用 `NOVELOS_RADAR_BOARDS` 只抓其中一类。
- `RankItem` 新增 `board`（`read` / `new`），旧数据迁移后为 `read`；`GET /api/radar/latest`、`GET /api/radar/trends` 支持 `?board=read|new`。
- 快照去重：同一 `rankVersion` 只有在榜单类型没有变多时才沿用旧快照（升级当天会补抓新书榜）。名次对比按「频道 + 榜类 + 题材 + 书」对齐。
- 示例数据增加 15 条虚构的新书榜条目。

### 风向标日报
- 新表 `TrendReport`；新规则包 `rules/trend_report.md` 与提示词 `prompts/trend_report.md`。
- 输入：每个总榜/题材按名次取前 N 本（书名、题材、标签、在读、名次变化、简介前 120 字），加上与上一快照比的新上榜与升幅最大（都由代码算）。
- 输出：热词（为什么火 + 例子书名）、四个总榜（总览 / 读者情绪 / 机会判断 / 写作建议 / 灵感切口）、开坑方向、标题句式、避坑提醒。程序校验：例子书名必须是榜上真实书名，否则删掉；没有真实例子的热词和标题句式整条作废；套话记 warning。
- API：`GET /api/radar/report?scope=`、`POST /api/radar/report`（Job）、`GET /api/radar/reports`。雷达配置新增 `auto_report`：刷新出新快照后自动提交日报任务。

### 平台风格档
- `Book.platform_style`：`fanqie`（默认）/ `qidian` / `generic`，建书与 PATCH 可设。
- `writing.md` 新增分平台小节，写作、精修、改写时按书的档注入：番茄档短段（1–3 行）、对白短句推进、开篇 200 字内切冲突、情绪直给、数字收益亮出来、章尾四种卡点、单章约 2000 字；起点档偏世界细节、配角智商与伏笔呼应。
- lint 按档调阈值（`app/lint/platform.py`）：番茄档放宽短句占比、平均句长、对话占比、单句段瀑布流（4→8）、群众反应镜头（3→5），收紧长段（>70 字的段落计问题并点名拆段）；描写增厚在番茄档不再合并短句。
- `humanize.md` 新增「去 AI 腔：读起来像人说话」一节（书面成语换口语、换掉 AI 标志动作、动词先行、长短句交替、不改情节/数值/对话结果）；词表新增「书面成语」类（只查叙述）。

### 审稿补丁
- 审稿输出新增 `patches[{index, original, improved, reason, issue_ref, severity, applied}]`，`original` 必须是正文逐字存在的连续片段。
- 写作流程：最后一轮审稿仍有 mid/high 问题且带补丁时，按原文逐字匹配逐个应用（匹配不到跳过并记录），旧正文进历史，重跑 lint，并记入 `review.patch_log` 与变更声明 warnings。
- 新接口 `POST /api/chapters/{id}/review/patches/apply {indices}`。`review_out` 保留 `reader` 字段。

### 书测
- `POST /api/books/{id}/book-test`（Job）出 A 番茄情绪爽感 / B 悬疑规则脑洞 / C 轻松沙雕 / D 起点正剧四组 `{style, title, subtitle(≤20字), hook, cover_prompt(3:4)}`，存在书上；`GET` 读取；`POST .../book-test/adopt {index, fields}` 写入书名/一句话简介（走作品信息版本栈，可撤回），可选写包装简介与封面提示词。
- Agent 新工具 `book_test`：产出「书测方案」提案（不会自动采纳），采纳时 `edited={index, fields}` 选一组，可撤回。

### 写章上下文
- 新增「后两章章纲」（标题、概要、伏笔动作、章末钩子；每章 ≤220 字、合计 ≤480 字），只用于提前埋线索，提示里禁止提前写出后面的事件。

### 其它
- 版本号 0.9.0。
