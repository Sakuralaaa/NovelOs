# 更新日志

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
