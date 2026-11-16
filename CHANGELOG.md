# 更新日志

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
