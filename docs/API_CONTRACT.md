# NovelOS v0.1 API 合约（前后端共同遵守）

后端：FastAPI，前缀 `/api`，JSON，UTF-8。时间 ISO8601。ID 为整数。
长任务（生成类）统一返回 `Job`，前端轮询 `GET /api/jobs/{id}`（或订阅 SSE `GET /api/jobs/{id}/events`，可选）。

## 通用
- `GET /api/health` → `{status:"ok", version}`
- 错误：`{detail: string}`，HTTP 4xx/5xx。

## Job
```
Job { id, kind: string, status: "queued"|"running"|"succeeded"|"failed", progress: 0-100, message: string,
      result: object|null, error: string|null, book_id: int|null, ref: string, created_at, updated_at }
```
- `ref`（v0.7.1）：任务关联的对象，如 `rank_item:12`；没有时为空串。
- `GET /api/jobs?book_id=&kind=&ref=` → Job[]（最新在前，最多 50；三个过滤都可选）
- `GET /api/jobs/{id}` → Job

## 模型渠道（设置页）
```
Channel { id, name, base_url, api_key_masked, models: string[], enabled: bool }
Routing { planner, writer, reviewer, embedding, image }  // 每项为 "channel_id:model" 字符串或 null
```
- `GET /api/settings/channels` / `POST` (body: name, base_url, api_key, models[]) / `PUT /{id}` / `DELETE /{id}`
- `POST /api/settings/channels/{id}/test` → `{ok, latency_ms, error?}`
- `GET /api/settings/routing` / `PUT /api/settings/routing`
- 未配置任何渠道时，后端使用内置 `mock` 渠道（确定性假数据），保证可演示。`GET /api/settings/status` → `{mock_mode: bool}`

## 热点雷达
```
RankItem { book_id_ext, title, author, category, rank, read_count, word_count, abstract, tags[], gender: "male"|"female" }
RadarSnapshot { id, taken_at, source: "app"|"web"|"mock", items_count }
TrendTopic { category, heat: number, books: int, rising: int, sample_titles[] }
```
- `POST /api/radar/refresh` → Job（抓取当日榜单；失败或关闭时用 mock）
- `GET /api/radar/snapshots` → RadarSnapshot[]
- `GET /api/radar/latest?gender=&category=` → `{snapshot, items: RankItem[]}`
- `GET /api/radar/trends` → TrendTopic[]
- `GET/PUT /api/radar/config` → `{enabled: bool, daily_hour: int}`

## 书（Book）
```
Book { id, title, genre, gender, tagline, status: "idea"|"bible"|"outline"|"writing"|"packaging"|"done",
       target_words: int, chapter_words: int, cover_url: string|null, created_at, updated_at,
       stats: { chapters: int, words: int, foreshadow_open: int } }
```
- `GET /api/books` / `POST /api/books` (title?, genre, gender, premise?) / `GET /api/books/{id}` / `PATCH` / `DELETE`

## 选题
```
Idea { id, book_id|null, title, logline, selling_points[], hook, genre, scores: {heat, novelty, fit, overall}, chosen: bool }
```
- `POST /api/ideas/generate` (body: {genre?, gender?, from_trends: bool, count: 3}) → Job（result: {idea_ids}）
- `GET /api/ideas` → Idea[]
- `POST /api/ideas/{id}/adopt` → Book（建书，status=bible）

## 设定库
```
Card { id, book_id, type: "world"|"power"|"faction"|"character"|"item"|"location",
       name, summary, data: object, known_by: string[], updated_at }
Fact { id, book_id, entity_id|null, key, value, from_chapter, to_chapter|null, visibility: "author"|"reader" }
```
- `POST /api/books/{id}/bible/generate` → Job
- `GET /api/books/{id}/cards?type=` / `POST` / `PUT /api/cards/{id}` / `DELETE /api/cards/{id}`
- `GET /api/books/{id}/facts`

## 大纲
```
OutlineNode { id, book_id, parent_id|null, level: "book"|"volume"|"arc"|"chapter", order, title, summary,
              beats: object|null, status: "planned"|"expanded"|"written", chapter_id|null }
```
- `POST /api/books/{id}/outline/generate` → Job（总纲 + 卷 + 前两弧 + 章细纲）
- `POST /api/outline/{node_id}/expand` → Job（滚动展开下一层）
- `GET /api/books/{id}/outline` → OutlineNode[]（平铺，前端组树）
- `PUT /api/outline/{node_id}`

## 章节
```
Chapter { id, book_id, number, title, content, words, status: "draft"|"reviewing"|"committed",
          review: Review|null, lint: Lint|null, updated_at }
Review { scores: {hook, pacing, payoff, character, coherence, overall}, issues: [{severity:"high"|"mid"|"low", dimension, quote, comment}], passed: bool }
Lint { ai_score: number, dialogue_ratio: number, repeated_ngrams: [{text,count}], banned_hits: [{word,count}], warnings: string[] }
（v0.6 附加，可选）Lint 另含 intensifiers: [{word,count,allow,over}], cliche_similes: [{word,count}], measure_errors: [{word,match,hint,quote}],
crowd_shots: number, dialogue_tics: [{word,count,over}], catchphrases: [{who,word,count,over}], fix_targets: [{kind,word,quote,hint}]；
Review.scores 另含 continuity（连续性与物理逻辑）、semantics（语义正确）；issue.dimension 可取这两个值。
Chapter.changes 可含 end_state: {cast:[{name,position,facing,holding[],wearing,body}], props:[{name,where,state}], env}（本章结束时的场景状态账本）。
ChangeSet { new_entities[], state_changes[], foreshadow: [{action:"plant"|"advance"|"resolve", id|null, desc}] }
```
- `GET /api/books/{id}/chapters` → Chapter[]（不含 content）
- `GET /api/chapters/{id}` → Chapter
- `PUT /api/chapters/{id}` (title, content) → Chapter（人工修改）
- `POST /api/books/{id}/chapters/write-next` → Job（取下一章细纲 → 写 → 检查 → 审稿 → 人味 lint → 定点重写 → 提交；result: {chapter_id}）
- `POST /api/books/{id}/chapters/write-batch` (count ≤ 10) → Job
- `POST /api/chapters/{id}/review` → Job；`POST /api/chapters/{id}/humanize` → Job；`POST /api/chapters/{id}/commit` → Job（v0.7.1 起；见文末 v0.7.1 增补）

## 伏笔
```
Foreshadow { id, book_id, desc, status: "planted"|"advancing"|"resolved"|"dropped", planted_ch, last_ch, resolved_ch|null }
```
- `GET /api/books/{id}/foreshadows`

## 包装与发布
```
Package { book_id, titles: [{title, score}], blurb, tags[], cover_prompt, covers: string[] /*url*/, chosen_cover|null }
```
- `POST /api/books/{id}/package/generate` → Job（书名候选、简介、标签、封面提示词）
- `POST /api/books/{id}/covers/generate` (prompt?, n=4) → Job（调用 image 路由，mock 时生成占位渐变 PNG）
- `GET /api/books/{id}/package` / `PUT`
- `GET /api/books/{id}/export` → zip 下载（建书资料.md、chapters/*.txt、cover.png、AI申报提示.md）

## 静态文件
- `/media/...` 封面图片等。

## v0.1 增补（2026-11-12 02:35，解决“AI 文像说明书、对话呆板、全是短句”）
- `Lint` 新增字段：`avg_sentence_len: number`、`short_sentence_ratio: number`（≤8 字句占比）、`bare_dialogue_ratio: number`（对白段前后无动作/神态/环境描写的比例）、`summary_ratio: number`（概述式叙述占比，估计值）。
- 风格卡：`GET/PUT /api/books/{id}/style` → `Style { sample_text: string /*用户粘贴的范文，≤5000 字*/, voice_notes: string, pov: "first"|"third", tone: string, extracted: object|null }`；`POST /api/books/{id}/style/extract` → Job（从范文提炼句长分布、描写密度、对话写法，存入 extracted）。
- 人物卡 `Card.data` 对 character 约定键：`voice`（说话方式）、`catchphrases[]`（口头禅）、`habits[]`（小动作）、`demeanor`（神态习惯）。
- 多版本：`write-next` body 可选 `{variants: 1|2|3}`（默认 1）。`Chapter` 新增 `variants: [{id, content, words, lint, review_overall}]`，status 为 `"draft"` 时作者挑选；`POST /api/chapters/{id}/adopt-variant` (variant_id) → Chapter。默认设置可选“自动采纳最高分”。
- 精修：`POST /api/chapters/{id}/thicken` → Job（“描写增厚”：只改写干对白/概述段落，补动作、神态、环境、心理，保持情节不变）。

## v0.4 增补：按要求让 AI 改

生成类接口均返回 Job，结果在 `job.result` 里，**不落库**；采纳类接口同步返回。`route` 为 `"渠道id:模型"`，不填走默认路由。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/books/{id}/revise` | `{instruction, route?}` → Job，result：`{current, proposal:{title,tagline,premise}, change, terms[], replacements{}, impact, trope_hits}` |
| POST | `/api/books/{id}/info` | 采纳作品信息 `{title?, tagline?, premise?, instruction}`，旧版本入栈 |
| POST | `/api/books/{id}/undo` | 撤回作品信息上一版 |
| POST | `/api/books/{id}/impact` | `{terms[]}` → `{terms, cards[], outline[], chapters[], total}` |
| POST | `/api/books/{id}/sync` | `{instruction, terms[], replacements{}, targets:["bible","outline"], route?}` → Job，result：`{bible: 设定建议|null, outline:{items[]}, chapters[]}` |
| POST | `/api/books/{id}/bible/propose` | `{mode: rewrite|add|optimize, instruction, route?}` → Job，result：`{mode, items[{key, action, card, target_id, old, conflicts[], trope_hits[], default}], removals[], facts[], counts}` |
| POST | `/api/books/{id}/bible/apply` | `{mode, instruction, ops:[{op:create|update|delete, card_id?, card?}], facts?}`，执行前自动快照 → `{created, updated, deleted, snapshot_id}` |
| GET | `/api/books/{id}/bible/snapshots` | 设定库快照列表 |
| POST | `/api/books/{id}/bible/snapshots/{sid}/restore` | 回滚（回滚前也存快照） |
| PUT | `/api/outline/{id}` | 新增可选 `instruction`；title/summary/beats 变化时旧版本入栈 |
| POST | `/api/outline/{id}/suggest` | `{instruction, route?}` → Job，result：`{current, proposal:{title, summary}, change}` |
| POST | `/api/outline/{id}/undo` | 撤回节点上一版 |
| POST | `/api/books/{id}/outline/apply` | 批量采纳 `{instruction, items:[{node_id, title?, summary?, beats?}]}` |
| POST | `/api/chapters/{id}/rewrite` | `{instruction, route?, scope: all|selection, start?, end?}` → Job，result：`{before, after, changed, ...}` |
| POST | `/api/chapters/{id}/apply-rewrite` | `{content, label?}`，旧正文进 history，重跑 lint |
| POST | `/api/chapters/{id}/undo` | 撤回到 history 最后一版 |
| GET | `/api/books/{id}/foreshadows/overview` | `{outline_planned[], committed, drafts, outline_nodes, last_committed}` |
| POST | `/api/books/{id}/foreshadows` | 手动新增 `{desc, status?, tier?, planted_ch?, resolved_ch?, plan_plant_ch?, plan_resolve_ch?, note?}` |
| PUT / DELETE | `/api/foreshadows/{id}` | 编辑 / 删除 |
| POST | `/api/books/{id}/foreshadows/plan` | `{instruction, route?, count}` → Job，result：`{items[{desc, tier, plant_ch, resolve_ch, note, related, duplicate_of, in_outline}]}` |
| POST | `/api/books/{id}/foreshadows/batch` | `{items[], attach}` → `{created, attached}`；状态为 planned，attach 时写进对应章细纲 |
| POST | `/api/ideas/{id}/detrope` | `{route?}` → Job（走整体修改，可撤回）；没命中禁用套路时 409 |
| GET / PUT | `/api/settings/tropes` | `{banned:[{name, keywords[]}]}`，GET 另返回 `defaults` |

输出增补：Book 增加 `premise`、`versions`、`last_instruction`、`banned_tropes`；Idea / Card（列表接口）增加 `trope_hits[{name, hits[]}]`；OutlineNode 增加 `versions`、`last_instruction`；Chapter 增加 `history`、`last_history_label`；Foreshadow 增加 `tier`、`plan_plant_ch`、`plan_resolve_ch`、`note`、`source`，`status` 新增 `planned`。PATCH `/api/books/{id}` 可改 `premise`、`banned_tropes`。


## v0.7 增补：榜单仿写（只学结构）

同步接口（直接返回结果，不走 Job）。榜单条目 `RankItem` 输出增加 `id`（`GET /api/radar/latest` 的 items 里），下面的 `{id}` 即它。

```
Teardown { id, rank_item_id, book_id_ext, title, created_at, cached: bool,
           teardown: { payoff_formula, golden_finger:{type, delivery}, protagonist_template, opening_hook, target_readers,
                       transferable[], must_replace[], warnings[] } | null,
           deep: { chapters[{index, title, words, dialogue_ratio, conflict, payoff, hook}], total_words, dialogue_ratio,
                   first_conflict:{keyword, at_char, chapter}|null, first_cheat:{keyword, at_char, chapter}|null,
                   rhythm, learnable[], overlap: int, warnings[] } | null }
```

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/radar/items/{id}/teardown?refresh=` | （v0.7.1 起返回 Job，result 为 Teardown）只用书名/简介/标签/品类/热度/名次变化拆解 → Teardown。按条目缓存（同一本书在别的快照拆过也复用，`cached=true`）；`refresh=true` 重拆 |
| GET | `/api/radar/items/{id}/teardown` | 读缓存 → Teardown；还没拆过 404 |
| POST | `/api/radar/items/{id}/deep` | （v0.7.1 起返回 Job，result 为 Teardown）`{text}` 试读原文，去空白后 ≤20000 字（超限或为空 400）→ Teardown（`deep` 已填）。字数/对白比例/首个冲突与金手指关键词位置由程序算（`at_char` 为去空白后第几字），每章冲突/爽点/钩子由模型补；原文不落库；模型输出与原文连续 8 字相同时 `warnings` 提醒 |
| POST | `/api/radar/items/{id}/reskin` | （v0.7.1 起返回 Job，result 为下述结构）基于拆解出 3 个换皮选题并存为 Idea → `{rank_item_id, teardown_id, ref_title, idea_ids[], ideas: Idea[], warnings[]}`；建书沿用 `POST /api/ideas/{id}/adopt` |

Idea 输出增加 `source`：普通选题为 `null`；仿写选题为 `{kind:"reskin", rank_item_id, ref_title, ref_book_id_ext, ref_category, kept[], changed[], self_check[{aspect, original, ours, similar}], overlap:{count, title, segments[]}, warnings[]}`。`warnings` 包括：与原书书名/简介连续 8 字相同、书名与原书连续 4 字相同、仍含「必须换掉的元素」、命中禁用套路、模型自检仍偏像。只提醒，不拦截。

Agent 新增提案工具 `imitate_rank_book`（`{rank_item_id?, title?}`）：拆解并出 3 个换皮选题，提案 kind=`reskin_ideas`，采纳后存进选题库（不改当前书），撤回删除未建书的那几个选题。

## v0.7.1 增补：长耗时模型接口改为任务（修 Cloudflare 524）

部署在 Cloudflare 等反向代理后面时，单个 HTTP 请求约 100 秒没响应就会被代理断开（524；Nginx 等为 502/504）。下面这些接口原来同步等模型，改为**立即返回 Job**，结果放在 `Job.result`，前端轮询 `GET /api/jobs/{id}`：

| 方法 | 路径 | Job.kind | Job.result | 进度文字（Job.message） |
|---|---|---|---|---|
| POST | `/api/radar/items/{id}/teardown?refresh=` | `radar_teardown` | Teardown（同 GET teardown；命中缓存时任务很快完成，`cached=true`） | 拆解中：《…》的爽点公式、金手指、人设 → 检查和简介的重合并保存 |
| POST | `/api/radar/items/{id}/deep` | `radar_deep` | Teardown（`deep` 已填） | 统计按章字数与对白比例 → 逐章拆解中（共 N 章）→ 检查和原文的重合并保存 |
| POST | `/api/radar/items/{id}/reskin` | `radar_reskin` | `{rank_item_id, teardown_id, ref_title, idea_ids[], ideas: Idea[], warnings[]}` | 读取拆解（没拆过时先拆）→ 生成选题 1/3 → 2/3 → 3/3 → 评分与相似点自检 → 保存到选题库 |
| POST | `/api/chapters/{id}/commit` | `chapter_commit` | `{chapter_id, number, chapter: Chapter（不含正文）}` | 生成本章摘要并写入底账 |

- 同步校验不变：榜单条目/章节不存在 404；深度拆解原文为空或超过 20000 字 400；章节正文为空 409。
- 三个仿写任务的 `Job.ref = "rank_item:{id}"`。同一本书同类任务（teardown / reskin）还在排队或运行时，再次 POST 直接返回那个进行中的 Job，不重复调用模型；deep 每次都新建任务。
- 新增 `GET /api/radar/items/{id}/jobs` → Job[]：这本书的仿写任务（最新在前，最多 20）。前端打开面板时用它找回进行中的任务、进度，以及最近一次成功的换皮结果。
- 换皮选题改为逐个生成（每次调用只出 1 个，并把本批已出的选题告诉模型拉开差异）。第 1 个失败则任务失败（`Job.error` 为原因）；后面的失败只少出几个，`warnings` 里写明「第 N 个选题生成失败：…」和「模型只给了 N 个选题」。
- Agent 工具 `imitate_rank_book` 不变（它本来就在 Agent 的后台任务里运行）。
- 前端：请求返回 502 / 504 / 524 时统一提示「服务器等待模型超时（可能被 Cloudflare 等代理截断），任务可能仍在后台运行」；任务失败显示后端 `Job.error`。


## v0.8 远程访问与调优

鉴权：除 Cookie 与 Basic 外，新增 API 密钥。`Authorization: Bearer nvk_<id>_<secret>` 或 `X-API-Key: nvk_…`。带密钥的写请求不做 Origin 校验。无效密钥返回 401「API 密钥无效或已删除」。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/auth/keys | `{keys:[{id,name,preview,created_at,last_used_at}], env_key_enabled}` |
| POST | /api/auth/keys | body `{name}` → 同上字段 + `token`（只返回这一次） |
| DELETE | /api/auth/keys/{id} | 删除 |
| GET | /api/prompts | 全部提示词与规则包：`{items:[{kind,name,overridden,chars,used_by}], system_base}` |
| GET | /api/prompts/{kind}/{name} | `{content(生效版本), default, overridden, used_by}`；kind 为 prompts 或 rules |
| PUT | /api/prompts/{kind}/{name} | body `{content}`，写入 data/prompt_overrides 并立即生效 |
| DELETE | /api/prompts/{kind}/{name} | 删除覆盖，恢复内置 |
| GET | /api/debug/llm-calls?task=&limit=&after_id= | 最近模型调用摘要（新的在前） |
| GET | /api/debug/llm-calls/{id} | 完整 messages、output、usage、耗时、错误 |
| DELETE | /api/debug/llm-calls | 清空 |

配置：`NOVELOS_API_KEY`（可选固定密钥，须 nvk_ 开头）、`NOVELOS_LLM_TRACE`（默认 1）、`NOVELOS_LLM_TRACE_MAX`（默认 200）。


## v0.9 新书榜、风向标日报、平台风格档、审稿补丁、书测

### 雷达
- `RankItem` 增加 `board: "read" | "new"`（阅读榜 / 新书榜；旧数据为 `read`）。
- `GET /api/radar/latest?gender=&category=&board=read|new` → `{snapshot, items:[RankItem], boards:["new","read"]}`（`boards`：这份快照里有哪几类榜）。
- `GET /api/radar/trends?gender=&board=read|new` → 同前；不传 board 时两类榜合并统计。
- `GET/PUT /api/radar/config`：增加 `auto_report: bool`（PUT 不传表示不改）。刷新结果 `Job.result` 增加 `boards:{read:n,new:m}`，开启自动日报时还有 `report_job_id`。

### 风向标日报
- `POST /api/radar/report` body `{scope?: "overall" | "category:<male|female>:<题材名>", top_n?: 3–30}` → Job（`kind=radar_report`，`ref=trend_report:<scope>`，另带 `job_id` 同 `id`）。同 scope 进行中的任务直接返回。scope 格式错 400；没有快照 409；题材不在最新快照里 404。`Job.result` 同下面的 TrendReport。
- `GET /api/radar/report?scope=overall` → TrendReport；没有 404（detail 说明怎么生成）。
- `GET /api/radar/reports?limit=10&scope=&full=false` → TrendReport[]，新的在前；`full=false` 时没有 `report`，改为 `hot_words:[string]`。

TrendReport：
```json
{"id":1,"snapshot_id":3,"scope":"overall","created_at":"…","model":"渠道名/模型名 或 mock","stale":false,
 "snapshot":{"id":3,"taken_at":"…","source":"web|app|mock","version":"…","items_count":0},
 "report":{
   "hot_words":[{"word":"","why":"","examples":["榜上真实书名"]}],
   "boards":[{"board":"男频阅读|男频新书|女频阅读|女频新书","overview":"","reader_mood":"","opportunity":"","writing_tips":"",
              "idea_hooks":[{"title":"","pitch":""}]}],
   "open_directions":[""],
   "title_patterns":[{"pattern":"《[极端条件]，我跑去[反差行为]》","examples":["榜上真实书名"]}],
   "pitfalls":[""],
   "warnings":["程序校验记录：删掉的凭空例子、缺的榜、套话"],
   "inputs":{"top_n":12,"books":0,"boards":{"男频阅读":12},"new_entries":{"男频阅读":0},"prev_snapshot_id":2}}}
```
题材日报的 `boards` 只有该频道的「阅读」「新书」两项。`stale=true` 表示已有更新的快照。

### 书与平台风格档
- Book 增加 `platform_style: "fanqie" | "qidian" | "generic"`（默认 fanqie）、`has_book_test: bool`。`POST /api/books`、`PATCH /api/books/{id}` 可设 `platform_style`。
- Lint 增加 `platform`（本次按哪一档检查）、`long_paragraphs`（超长段落数，番茄档 >70 字）；`fix_targets` 可能出现 `kind:"长段"`。

### 审稿补丁
- Review 增加 `patches:[{index, original, improved, reason, issue_ref(int|null，对应 review.issues 下标), severity, applied}]` 与 `patch_log:[{label:"自动修|作者应用", at, applied:[index], skipped:[{index, reason}]}]`。`reader` 字段照常返回。
- `write-next` 的 `Job.result` 增加 `review_patches:{applied:[index], skipped:[{index, reason}]}`（只自动应用对应 mid/high 问题的补丁；不重新审稿）。
- `POST /api/chapters/{id}/review/patches/apply` body `{indices:[int]}`（1–20 个）→ `{chapter: Chapter, applied:[{index, original, improved}], skipped:[{index, reason}]}`。同步、不调模型；逐字匹配原文，匹配不到 / 已应用的跳过；旧正文进历史，可 `POST /api/chapters/{id}/undo`。没有补丁 409。预览由前端用 `patches` 自己做。

### 书测
- `POST /api/books/{id}/book-test` → Job（`kind=book_test`），`result` 同 GET。
- `GET /api/books/{id}/book-test` → `{book_id, variants:[{style:"A 番茄情绪爽感|B 悬疑规则脑洞|C 轻松沙雕|D 起点正剧", title, subtitle(≤20字), hook, cover_prompt(含 3:4)}], warnings:[], created_at, model, adopted:int|null, adopted_fields:[]}`；没做过 404。
- `POST /api/books/{id}/book-test/adopt` body `{index, fields?:["title","subtitle","hook","cover_prompt"]}`（默认 `["title","subtitle"]`：title→书名，subtitle→一句话简介，hook→包装简介，cover_prompt→包装封面提示词）→ `{book, package, adopted:{index, variant, applied, before, after}}`。书名/简介走作品信息版本栈，可 `POST /api/books/{id}/undo` 撤回。下标越界 404。
- Agent 工具 `book_test`：产出 `kind:"book_test"`（标签「书测方案」）提案，`needs_review=true`（自动采纳不会替作者选）；`payload.variants` 为四组方案。采纳 `POST /api/agent/proposals/{pid}/apply` body `{edited:{index, fields?}}`，可撤回。


## v0.9.1 榜单书架化、单书详情与灵感、朱雀 AIGC 检测、语感重塑

### 雷达列表项（RankItem）新增字段
`GET /api/radar/latest` 的 `items[]`（以及 `detail.item`）在原有字段外增加：

| 字段 | 类型 | 说明 |
|---|---|---|
| `cover` | string \| null | 本站封面代理相对路径 `/api/radar/cover/{book_id_ext}`；该书没有封面地址时为 null |
| `source_url` | string \| null | `https://fanqienovel.com/page/{bookId}`；示例数据（非数字 id）为 null |
| `first_chapter_url` | string \| null | `https://fanqienovel.com/reader/{firstChapterItemId}`；没有首章 id 时为 null |
| `chapter_count` | int | 从最新章标题解析的章号估计，0 表示未知 |
| `last_chapter_title` | string | 最新章标题，可能为空串 |
| `last_update_at` | ISO8601 \| null | 最新章更新时间（UTC） |
| `first_chapter_id` / `last_chapter_id` | string | 番茄章节 itemId，可能为空串（额外字段，可不用） |

> 偏离说明：`source_url` / `first_chapter_url` 在示例数据或缺 id 时为 null（契约原文写作 string）。

### 封面
- `GET /api/radar/cover/{book_id_ext}` → 图片（`image/jpeg` 或 `image/png`，按文件头），`Cache-Control: private, max-age=2592000, immutable`；没有封面地址 / 下载失败 / 非图片 / 超过 2MB / id 不合法 → 404 JSON。
- 鉴权与其它 `/api` 相同（登录 Cookie 或 API 密钥）。前端同源 `<img src={item.cover}>` 会自动带 HttpOnly 会话 Cookie，无需单独放行；用 API 密钥的脚本请带 `Authorization: Bearer nvk_…` 或 `X-API-Key`。
- 抓榜成功后后台预缓存本次快照的封面（配置 `NOVELOS_RADAR_CACHE_COVERS`，默认开）。

### 单书详情
- `GET /api/radar/books/{book_id_ext}/detail?refresh=false` →
```json
{"item": {"…列表项全部字段": ""},
 "chapter_total": 412,
 "abstract": "书页上的完整简介（取不到时为条目简介）",
 "chapters_head": [{"title": "第1章 …", "item_id": "7654…", "url": "https://fanqienovel.com/reader/7654…"}],
 "chapters_tail": [{"title": "第412章 …", "item_id": "…", "url": "…"}],
 "fetched_at": "2026-11-16T09:00:00Z",
 "detail_error": null,
 "cached": false}
```
- `chapters_head` 为前 50 章；`chapters_tail` 为第 50 章之后的最后 10 章（总数 ≤50 时为空数组，两者不重复）。`chapter_total` 取不到时为 null。
- 解析结果缓存 24 小时（`refresh=true` 强制重抓）。抓取失败时 HTTP 仍为 200：返回 `item`，`detail_error` 为中文原因，其余为空。示例数据 `detail_error="示例数据没有番茄书页"`。榜单里没有这本书 → 404。
- 额外字段 `cached: bool`。

### 单书 AI 灵感
- `POST /api/radar/books/{book_id_ext}/ai` body `{kind: "title" | "cover" | "blurb", n?: 1–10}`（n 默认 title/blurb 5、cover 3）→ Job（`kind=radar_book_ai`，`ref=radar_book:{id}:{kind}`；返回体同 Job 并带 `job_id` 同 `id`）。同书同 kind 进行中的任务直接返回。kind 不合法 / n 越界 422；书不存在 404。
- `Job.result`：
```json
{"kind": "title", "book_id_ext": "…", "ref_title": "原书名",
 "candidates": [{"title": "", "why": ""}],
 "dropped": 0,
 "warnings": ["已丢弃「…」：和原书名/简介有 1 处连续 8 字相同（…）"]}
```
  - title → `[{title, why}]`；cover → `[{prompt, style}]`（prompt 一段中文画面描述，含「竖版 3:4」，可直接作为 `POST /api/books/{id}/covers/generate` 的 `prompt`）；blurb → `[{blurb, hook}]`。
  - 查重：与原书名+原简介连续 8 字相同 ≥1 处丢弃；书名候选与原书名连续 4 字相同或包含原书名也丢弃。`dropped` 为丢弃数，候选可能少于 n。
- 提示词：`prompts/radar_book_title`、`radar_book_cover`、`radar_book_blurb`（`/api/prompts` 可覆盖）。

### 朱雀 AIGC 检测（只做检测）
- `GET /api/settings/zhuque` → `{zhuque_configured: bool, zhuque_key_tail: string(尾号 4 位，未配置为空串), zhuque_base_url: string, zhuque_auto_check: bool, zhuque_usage: {calls, tokens}}`。
- `PUT /api/settings/zhuque` body 任选 `{zhuque_api_key?: string（空串=清除）, zhuque_base_url?: string（空串=恢复默认 https://ai-gateway.edgeone.link）, zhuque_auto_check?: bool}` → 同 GET。局部更新，不传的项不变；地址不是 http(s) 开头 400。
  > 偏离说明：这组设置是独立接口 `/api/settings/zhuque`，不混在 `/api/settings/writing` 里。
- `POST /api/detect/aigc` body `{text: string(1–200000), is_merge?: true}` → Job（`kind=aigc_detect`，带 `job_id`）；未配置密钥 409。`Job.result` = 下方 Aigc 结构去掉 `checked_at` / `content_hash` / `stale`，多 `chars`、`is_merge`。
- `POST /api/books/{book_id}/chapters/{chapter_id}/aigc` body 可选 `{is_merge?: true}` → Job（`kind=chapter_aigc`，`ref=chapter:{id}`，带 `job_id`）；章节不属于该书 404、正文为空 409、未配置密钥 409。`Job.result = {chapter_id, aigc: Aigc}`，同时写入章节。
- 章节（`GET /api/chapters/{id}` 等返回 Chapter 的接口）新增 `aigc: Aigc | null`；章节列表里的 `aigc` 不带 `segments`。

Aigc：
```json
{"checked_at": "2026-11-16T09:00:00.000000Z",
 "content_hash": "sha256 前 16 位",
 "stale": false,
 "softmax": 0.91,
 "ratio": 0.7,
 "labels_ratio": {"human": 0.1, "ai": 0.7, "suspect": 0.2},
 "level": "low | mid | high",
 "ai_segment_ratio": 0.54,
 "suspect_segment_ratio": 0.1,
 "segments": [{"start": 0, "end": 12, "label": "human | ai | suspect", "conf": 0.97}],
 "tokens": 1234,
 "chunks": 1,
 "chars": 2300,
 "is_merge": true}
```
- `level` 按 softmax：<0.5 low、0.5–0.85 mid、≥0.85 high。`segments` 的 start/end 是全文字符偏移（`content.slice(start, end)`）。`ai_segment_ratio` / `suspect_segment_ratio` 为分段里 AI / 疑似段的字数占比（没有分段时 null）。`stale=true` 表示检测后正文改过（服务端按 content_hash 判断）。
- 失败（Job failed）的 `error` 为中文：密钥无效（401/403）、额度/频率（429）、超时（30 秒）等。
- 写章流程不自动调用；`zhuque_auto_check=true` 时章节提交后后台检测一次，失败不影响提交。不提供“分高就自动改写”。

### 语感重塑
- `POST /api/books/{book_id}/chapters/{chapter_id}/polish-voice`（无 body）→ Job（`kind=chapter_polish_voice`，带 `job_id`）；章节不属于该书 404、正文为空 409。
- `Job.result`（与 `POST /api/chapters/{id}/rewrite` 的对比稿结构一致，另加 `label`、`checks`、`warnings`）：
```json
{"chapter_id": 1, "scope": "all", "start": 0, "end": 2300, "instruction": "语感重塑", "label": "语感重塑前",
 "before": "原文", "after": "润色稿", "changed": true, "words_before": 2300, "words_after": 2250, "ai_score_after": 21.5,
 "checks": {"numbers_missing": [], "numbers_added": [], "names_checked": ["林恩"], "names_missing": [], "words_ratio": -0.022, "long_paragraphs": 0},
 "warnings": ["数字/数值和原文不一致（少了 三千；多了 3000），请核对…"]}
```
- 不改正文。采纳：`POST /api/chapters/{id}/apply-rewrite {content: after, label}`；撤回：`POST /api/chapters/{id}/undo`。
- 偏离说明：没有 `draft_id`，沿用现有对比稿结构（before/after）。
- Agent 工具 `polish_voice`（参数 `number` 或 `chapter_id`）：产出 `kind:"chapter_rewrite"` 提案，`payload` 同改写提案并多 `warnings`、`checks`，`payload.instruction="语感重塑"`。

### 版本
- `GET /api/health` → `version: "0.9.1"`。


## v0.9.2 榜单 → 立项：日报升级、按榜日报、种子立项、一键整理、多本熔炉、仿写 TXT

所有调模型的接口都返回 Job（返回体同 Job，另带 `job_id` 同 `id`），结果在 `Job.result`；用 `GET /api/jobs/{id}` 轮询。

### 风向标日报 schema 升级
`TrendReport.report` 保留 v0.9 的全部字段（`hot_words`、`boards[].overview/reader_mood/opportunity/writing_tips/idea_hooks`、`open_directions`、`title_patterns`、`pitfalls`、`warnings`、`inputs`），旧报告原样返回（没有下列新字段，前端按缺省处理）。新增：
```json
{"headline": "灵异职业化与系统返还双主线，弱起点强结算最吃香",
 "summary": "2–3 句总述",
 "boards": [{"board": "男频阅读", "overview": "", "reader_mood": "", "opportunity": "", "writing_tips": "",
             "risks": "风险提醒（字符串，可能为空）",
             "idea_hooks": [{"title": "", "pitch": ""}]}],
 "inspirations": [{"title": "", "logline": "一句话钩子", "protagonist": "", "mechanism": "", "opening": "第一章开局",
                   "selling_points": ["", "", ""], "board": "男频阅读"}],
 "opening_hooks": ["开篇钩子写法"],
 "plot_devices": [{"name": "倒计时结算", "desc": ""}],
 "writing_advice": "整体写作建议",
 "risk_alerts": ["风险提醒"],
 "meta": {"scope": "overall", "top_n": 30, "books_read": 96, "abstract_chars": 80},
 "inputs": {"top_n": 30, "books": 110, "books_read": 96, "boards": {"男频阅读": 30}, "new_entries": {}, "prev_snapshot_id": 2}}
```
- `headline` ≤40 字；`summary` ≤300 字。`inspirations` 目标 4–6 条（最多 6；不足 4 条时 `warnings` 里有记录）；`board` 可省略（模型没写或不是本次 scope 的榜）。每条 `selling_points` 最多 3 条。
- 灵感卡查重：和榜上书重名的删掉；与榜上书名+完整简介做 v0.7 的 8 字 n-gram 比对，有 ≥1 处连续 8 字相同就删，记一条 `warnings`。
- `idea_hooks` 兼容：模型给了就用模型的；某个榜没给时由归到该榜的 `inspirations` 派生（`title`、`pitch=logline`）；单榜日报（board / category 带榜）所有灵感卡都算这个榜。
- `opening_hooks` ≤5、`plot_devices` ≤5、`risk_alerts` ≤6。
- `meta.top_n` 为每榜读的本数上限，`meta.books_read` 为实际读进各榜的不同书数；`inputs.books` 仍为输入里出现过的全部书名数（含新上榜/升幅榜）。

### 报告 scope
| scope | 读哪些榜 |
|---|---|
| `overall` | 四个总榜（男频阅读/男频新书/女频阅读/女频新书），各按在读取前 N 本 |
| `board:<male\|female>:<read\|new>` | 只读该频道该榜（跨题材按在读取前 N 本），`boards` 只有一项 |
| `category:<male\|female>:<read\|new>:<题材名>` | 该题材的该榜，按名次取前 N 本，`boards` 只有一项 |
| `category:<male\|female>:<题材名>` | 旧写法，保持 v0.9 行为：该题材阅读榜 + 新书榜 |

- `POST /api/radar/report` body `{scope?, top_n?: 3–50}`（不传 top_n 用配置 `radar_report_top_n`，默认 30）→ Job（`kind=radar_report`，`ref=trend_report:<scope>`）。scope 格式错 400；没有快照 409；题材不在最新快照 / 该频道没有该榜 404。
- `GET /api/radar/report?scope=…`，以及别名 `GET /api/radar/report/latest?scope=…` → TrendReport；没有 404。
- `GET /api/radar/reports?scope=…&limit=&full=` 照旧。
- 报告按请求时的 scope 字符串存，查询按同一字符串匹配。

> 偏离说明：任务说明里写「旧的 `category:<gender>:<name>` 视为 read」，但 v0.9 的旧写法一直是「阅读榜 + 新书榜」（已有测试与历史报告都按这个），为了旧报告和旧前端不变，旧写法保持两榜；要只看阅读榜请用 `category:<g>:read:<题材>`。

### 日报配置
- `GET /api/radar/report/config` → `{radar_report_top_n: int(3–50，默认 30), radar_report_auto_scopes: string[]（默认 ["overall"]）}`。
- `PUT /api/radar/report/config` body 任选 `{radar_report_top_n?, radar_report_auto_scopes?: string[]（≤8 个）}` → 同 GET。局部更新；scope 格式不对 400；重复项去掉。
- 自动日报开关仍是 `/api/radar/config` 的 `auto_report`（该接口形状不变）。开启时，每次刷新出新快照后，对 `radar_report_auto_scopes` 里这份快照还没有日报、且在快照里存在的 scope 各提交一个任务。刷新 `Job.result` 新增 `report_job_ids: {scope: job_id}`；`report_job_id` 仍是 overall 那个（若有）。
- 环境变量默认值：`NOVELOS_RADAR_REPORT_TOP_N`、`NOVELOS_RADAR_REPORT_AUTO_SCOPES`（存库的值优先）。

> 偏离说明：这两个配置放在独立接口 `/api/radar/report/config`，没有并进 `/api/radar/config`（避免改变旧接口返回形状）。

### 种子立项
`POST /api/ideas/from-seed` body：
```json
{"title": "必填 ≤60", "logline": "必填 ≤500", "protagonist": "可选", "mechanism": "可选", "opening": "可选",
 "selling_points": ["可选，≤8 条"], "genre": "可选", "gender": "male|female（可选）",
 "source": {"type": "trend_report|rank_book|paste|fusion|manual", "ref": "可选 ≤200", "report_id": 1, "book_id_ext": "可选"},
 "expand": false}
```
- `expand=false`：同步、不调模型 → `{idea: Idea}`。映射：`title`（去书名号，≤40）、`logline`、`selling_points`（前 4 条）、`hook ← opening`、`genre`、`gender`（不传时取参考书的频道，否则 male）；`expectations/arc` 为空、`endgame` 为空串、`scores` 留空（Idea 里显示为 0）。
- `expand=true`：Job（`kind=idea_seed`）→ `result {idea: Idea, idea_id}`。planner 按 `/ideas/generate` 的 Idea 结构与禁用套路清单扩写，并做复核打分。
- `source.book_id_ext` 给了但榜单里没有 → 404；`source.report_id` 给了但日报不存在 → 404；`source.type` 不在枚举内 → 422。
- 建书（`POST /api/ideas/{id}/adopt`）时，种子的 `protagonist` / `mechanism` 会并进书的 `premise`（「主角：…」「核心机制：…」）。

Idea.source（种子立项）：
```json
{"type": "trend_report", "kind": "trend_report", "ref": "灵感卡#2 | trend_report#<report_id> | rank_book:<book_id_ext> | null",
 "report_id": 1, "book_id_ext": "…",
 "seed": {"title": "", "logline": "", "protagonist": "", "mechanism": "", "opening": "", "selling_points": [], "genre": ""},
 "expanded": true,
 "change": "相对种子改了什么（仅 expand）",
 "self_check": [{"aspect": "书名", "kept": true, "note": ""}],
 "overlap": [{"ref": "《参考书》", "count": 1, "segments": ["…"]}],
 "warnings": ["和《…》的书名/简介有 1 处连续 8 字相同…", "命中禁用套路：…"]}
```
`ref` 不传时按 report_id / book_id_ext 自动生成。`overlap` 只在有参考书（book_id_ext）时出现。所有 v0.9.2 的 Idea.source 都带 `type` 与 `ref`；`kind` 与 v0.7 的 `source.kind` 兼容（换皮选题仍是 `kind:"reskin"`，没有 `type`）。

### 一键整理
- `POST /api/ideas/organize` body `{text: 1–5000 字, genre?, gender?}` → Job（`kind=idea_organize`）→ `result {idea: Idea, idea_id}`。超过 5000 字 422；全是空白 400。
- 不改作者的核心设定（主角、名字、机制、世界规则、关系、结局），只理顺、补齐缺的字段；作者给了书名就用。
- Idea.source：`{type:"paste", kind:"organize", ref:"原文前 60 字摘录", chars, kept_core:[], added:[], conflicts:[], warnings:[]}`。`warnings` 可能有「作者原有设定在整理稿里没找到原词，请核对」。原文只存前 60 字摘录。

### 多本熔炉
- `POST /api/ideas/fusion` body `{refs: [{book_id_ext?, title?, text?(去空白后 ≤20000 字), weight: >0}] (1–3 本), notes?: ≤1000, n?: 1–5（默认 3）}` → Job（`kind=idea_fusion`）。
- 同步校验：refs 为空或多于 3 本 422；weight ≤0 422；某本既没有 book_id_ext 也没有 title、text 400；book_id_ext 不在榜单 404；text 超过 20000 字 400。
- `weight` 归一化（合计 1，保留 3 位小数）。`book_id_ext` 取最新那条榜单记录的书名/简介/标签/题材，以及 v0.7 已有的拆解 / 深度拆解（有就带）。`text` 只在本次使用，不入库（每本最多 6000 字进提示词，查重用全文）。
- `Job.result`：
```json
{"ideas": [Idea], "idea_ids": [1, 2], "dropped": 1,
 "warnings": ["已丢弃《…》：和参考2《…》有 1 处连续 8 字相同（…）", "《…》：书名和《…》连续 4 字相同", "只留下 2 个选题（要求 3 个，丢弃 1 个）"]}
```
- 查重：每个结果与每本参考的「书名+简介+text」做 8 字 n-gram，≥1 处相同就丢弃并计入 `dropped`；书名与参考书名连续 4 字相同只提醒。
- Idea.source：`{type:"fusion", kind:"fusion", ref:"《A》×0.75；《B》×0.25", refs:[{index, title, book_id_ext, weight, has_text}], notes, borrowed:[{ref:"参考1", what}], changed:[], overlap:[], warnings:[]}`（没有书名的粘贴参考在 ref 里写作「粘贴原文{序号}」）。

### 仿写立项 TXT
- `POST /api/radar/imitate/extract`：`multipart/form-data`（字段 `file`=TXT，≤30MB）或 JSON `{text, filename?}` → 同步返回（不入库、不调模型）：
```json
{"title_guess": "雾港夜巡人", "encoding": "utf-8|utf-8-sig|utf-16|gb18030|text",
 "total_chapters": 120,
 "chapters": [{"title": "第1章 夜巡", "chars": 2100}],
 "text": "前 10 章「标题\n\n正文」用空行拼接，≤20000 字",
 "text_chars": 19876, "truncated": false}
```
- 编码：有 BOM 按 BOM；否则先 utf-8，失败按 gb18030（兼容 gbk）。切章识别「第X章 / 第X回 / 第X节」（中文或阿拉伯数字）、「Chapter N」（不分大小写）、序章 / 楔子 / 引子；第一个章节标题前的内容（书名、作者、简介）不进 `text`。识别不到章节时整段算一章 `{"title":"全文"}`，`total_chapters=0`。`chapters` 只列前 10 章，`chars` 为去空白字数。`truncated=true` 表示前 10 章超过 20000 字被截断。
- `title_guess`：开头的「书名：X」或「《X》」→ 文件名（去掉括号里的「全本」「作者」等）→ 开头第一行短文字。
- 空文件 / 只有空白 / JSON 没有 text / 其它 content-type 400。
- 前端拿 `text` 走现有 `POST /api/radar/items/{id}/deep`（深度拆解）与 `POST /api/radar/items/{id}/reskin`。

### 提示词
新增 `prompts/idea_seed`、`idea_organize`、`idea_fusion`；`prompts/trend_report` 与规则包 `rules/trend_report` 升级（可在 `/api/prompts` 覆盖；已有覆盖的旧版 trend_report 仍可用，只是不会产出新字段）。

### 版本
- `GET /api/health` → `version: "0.9.2"`。

## v0.9.3 作品完整度、新手引导、字段级 AI 与 @引用、角色灵魂五维、审批模式与成本提示、拆书工作台

> 前端按本节对接。所有调模型的接口都返回 Job（`POST` 立即返回 `{id, kind, status, ...}`，结果在 `Job.result`），用现有 `/api/jobs/{id}`（或 SSE）轮询。

### 设定条目（Card）新增字段
```
Card { ...原有字段,
       status: "active" | "deprecated",      // 默认 active；旧库补列为 active
       ref_enabled: boolean,                  // 默认 true；false 时不出现在 @ 补全、@ 不注入
       soul: Soul | null }                    // 仅 character 有意义；其它类型恒为 null
Soul { desire: string, fear: string, wound: string, belief: string, voice: string }   // 欲望/恐惧/伤痕(过去)/信念(底线)/说话方式；每项可为空串
```
- `GET /api/books/{id}/cards?type=&include_deprecated=false`：**默认不含** deprecated；传 `include_deprecated=true` 返回全部（设定库管理页应传 true，用 `status` 显示「已弃用」并可恢复）。
- `POST /api/books/{id}/cards`、`PUT /api/cards/{id}` 可带 `status`、`ref_enabled`、`soul`。`soul` 按键合并：只改传了的键；传空串清空该项；传 `soul: {}` 不变。非 character 条目传 soul 忽略。
- deprecated 条目不进任何生成上下文（写作、章纲、场景、大纲、Agent 读设定、审稿等），也不出现在 refs。

### 字段级 AI（不直接写库）
- `POST /api/books/{id}/bible/{entry_id}/field-ai` body `{field, instruction?: ≤500, mode: "fill"|"rewrite"|"expand", route?}` → Job（`kind=field_ai`）。
  - `field`：`name` | `summary` | `data.<key>`（如 `data.appearance`）| `soul.<desire|fear|wound|belief|voice>`。其它 422；条目不属于本书 404；`soul.*` 用在非角色条目 400。
  - `fill`：字段为空时补写（字段已有内容也会给一个补全版）；`rewrite`：按 instruction 改写；`expand`：在原内容基础上扩写。
  - `Job.result`：`{entry_id, field, mode, before, value, note}`。`before` 为当前值（不存在为 ""），`value` 为建议值（字符串；`data.<key>` 原值是数组时返回数组）。
- 采纳：`POST /api/books/{id}/bible/{entry_id}/field-ai/apply` body `{field, value}` → Card（同步写库，写前自动存设定快照，可用已有快照回滚）。也可以继续用 `PUT /api/cards/{id}` 自己拼。

### @引用
- `GET /api/books/{id}/refs?q=&limit=20` → `[{id, name, type, type_label, brief}]`。只含 `status=active` 且 `ref_enabled=true`；`q` 为名称包含匹配（空串返回全部，按类型、id 排序）；`brief` 为一句话（summary 前 40 字）；`limit` 1–100。
- 生成时，章节计划 / 大纲节点概要 / 用户指令（写章 instruction、改写 instruction、Agent 消息等）里出现 `@条目名` 的，把该条目完整内容（summary + data + soul）注入提示词「@引用设定」段。按名称最长优先匹配；未命中的 @ 忽略。

### 角色灵魂五维
- `POST /api/books/{id}/characters/{entry_id}/soul` body `{mode?: "fill"|"rewrite"（默认 fill）, instruction?: ≤500, route?}` → Job（`kind=character_soul`）→ `result {entry_id, mode, before: Soul, soul: Soul, note}`。fill 只补空项（已有项原样保留），rewrite 全部重写。**不写库**；采纳用 `PUT /api/cards/{id}` `{soul}`。非 character 条目 400。
- 写作 / 场景 prompt 里，本章出场角色带一行简短五维（每项 ≤30 字）。

### 作品完整度
`GET /api/books/{id}/completeness` →
```json
{"book_id": 1, "score": 65,
 "items": [{"key": "overview", "label": "概览与一句话卖点", "done": true, "weight": 10, "hint": "", "action": {"type": "route", "target": "/books/1"}}]}
```
- 10 项各 10 分（`score` 为 done 项权重之和，主角卡有卡但五维不全时得 5 分、done=false）：
  | key | label | done 条件 | action |
  |---|---|---|---|
  | `overview` | 概览与一句话卖点 | tagline 与 premise 都非空 | route `/books/{id}` |
  | `world` | 世界观 | 有 active 的 world 或 power 条目 | job `/api/books/{id}/bible/generate` |
  | `protagonist` | 主角卡（含灵魂五维） | 有主角卡且 soul 五项全非空 | 无主角：job bible/generate；有主角缺五维：job `/api/books/{id}/characters/{cid}/soul` |
  | `supporting` | 配角≥2 | 主角之外 active 角色 ≥2 | route `/books/{id}/bible` |
  | `factions_locations` | 势力/地点 | 有 active 的 faction 或 location | route `/books/{id}/bible` |
  | `outline` | 大纲 | 有非 chapter 级大纲节点 | job `/api/books/{id}/outline/generate` |
  | `chapter_plans` | 前三章章纲 | 第 1–3 章的 chapter 级节点都有 summary | route `/books/{id}/outline` |
  | `chapter1` | 第 1 章 | 第 1 章存在且正文非空 | job `/api/books/{id}/chapters/write-next` |
  | `title_blurb` | 书名与简介 | 书名不是「未命名作品」且（包装 blurb 或 tagline）非空 | route `/books/{id}/package` |
  | `cover` | 封面 | book.cover_url 或包装 chosen_cover 非空 | route `/books/{id}/package` |
- `action.type="route"`：`target` 是前端路由；`"job"`：`target` 是要 `POST`（空 body）的接口路径，返回 Job。`hint` 为未完成时的一句提示，完成时为空串。

### 新手引导（全局）
- `GET /api/onboarding` → `{steps: {model, project, bible_outline, first_chapter: bool}, order: ["model","project","bible_outline","first_chapter"], labels: {key: "中文名"}, auto: {key: bool}, current: key|null, dismissed: bool}`。
  - `auto` 按实际数据判定：`model` 有启用且有模型的渠道；`project` 至少一本书；`bible_outline` 某本书有设定条目且有大纲节点；`first_chapter` 某本书有正文非空的章节。`steps[k] = auto[k] || 手动标记[k]`。`current` 为第一个未完成的步骤（全完成为 null）。
- `PUT /api/onboarding` body `{steps?: {key: bool}, dismissed?: bool}` → 同 GET。未知 key 422。存设置（KV `onboarding`）；手动标 false 不能覆盖 auto 判定的 true。

### 审批模式
- Book 新增 `approval_mode: "auto"|"review"`（`GET/PATCH /api/books/{id}`）。旧书按 `agent_auto_apply` 映射：true→auto，false→review。PATCH `approval_mode` 时同步 `agent_auto_apply`；只 PATCH `agent_auto_apply` 也同步 approval_mode（两字段始终一致）。
- `review`：Agent 改动一律提案（不自动采纳）；章节 AI（写章多版本、改写、去 AI 味 humanize、加厚 thicken、语感重塑、审稿补丁）只生成对比稿/版本/提案，不自动落库、不自动采纳最佳版本、不自动提交。写章 Job 结果额外带 `approval_mode`。
- `auto`：照旧（遵循全局写作设置 auto_adopt_best / auto_commit）。

### 成本提示
- `POST /api/estimate` body `{kind, book_id?, chapter_id?, words?}` → 
```json
{"kind": "chapter_write", "input_tokens_est": 5200, "output_tokens_est": 3300, "calls_est": 4,
 "route": "writer", "model": "渠道名/模型名 | mock", "seconds_est": 95, "seconds_source": "history|default", "note": "…"}
```
  - `kind`：`chapter_write` `chapter_rewrite` `polish_voice` `humanize` `thicken` `review` `outline` `bible` `report` `idea` `field_ai` `soul` `teardown` `package`；其它 422。需要书/章的 kind 没给对应 id 时用通用默认值并在 note 说明；id 不存在 404。
  - 输入按真实组装的上下文长度估（中文按 1 字≈`tokens_per_char` token，默认 1.0，环境变量 `NOVELOS_TOKENS_PER_CHAR`）；输出按目标字数（`words` > 书的 `chapter_words` > 2200）。`seconds_est` 为 llm_usage 里同 route 最近 20 次平均耗时 × calls_est（`seconds_source=history`），没记录用默认（`default`）。
- `GET /api/books/{id}/usage` → `{book_id, calls, in_tokens, out_tokens, ms, by_kind: [{kind, calls, in_tokens, out_tokens, ms}], by_route: [{route, calls, in_tokens, out_tokens, ms}], last_at: iso|null}`。
- `GET /api/usage?days=30` → 全局同形状（`book_id: null`）。
- 数据来自新持久表 `llm_usage(route, model, book_id, kind, in_tokens, out_tokens, ms, estimated, created_at)`：每次模型调用（含 mock）记录一条，`kind` 为所在任务的 Job.kind，`book_id` 为任务所属书；渠道没返回 usage 时按字数估算并标 `estimated`。

### 拆书工作台
```
Teardown { id, title, source: "rank_book"|"paste"|"txt", book_id_ext: string|null, chars: int,
           result: { structure: {opening, rhythm, chapter_hooks: string[]},
                     characters: [{role, template, traits: string[], function}],
                     golden_finger: {mechanism, limits, growth, payoff},
                     selling_points: string[],
                     pacing_chart: [{chapter: int, title, conflict: 1-5, payoff: 1-5, hook: 1-5, note}],
                     reusable: [{name, pattern, how_to_use}] },
           warnings: string[], model, created_at }
```
- `POST /api/teardowns` body `{source, book_id_ext?, text?(去空白后 ≤20000 字), title?}` → Job（`kind=teardown_project`）→ `result {teardown: Teardown, teardown_id}`。
  - `rank_book`：`book_id_ext` 必填且须在榜单（否则 404），`text` 可选（试读原文），没 text 时用榜单元信息 + v0.7 已有拆解。`paste`/`txt`：`text` 必填（空 400）。text 超 20000 字 400；source 不在枚举 422。title 不传时取榜单书名或「拆书 #序号」。
  - **原文不入库**，只存产物；产物里去掉原书专名（书名、作者、模型回报的人名/地名等）；产物每条与原文做 8 字 n-gram 比对，有相同片段的条目删掉并记 `warnings`。`pacing_chart` 强度值夹到 1–5，按章号排序（最多 60 章）。
- `GET /api/teardowns` → `[{id, title, source, book_id_ext, chars, created_at, warnings_count, modules: [有内容的模块名]}]`（新的在前）。
- `GET /api/teardowns/{id}` → Teardown；`DELETE /api/teardowns/{id}` → `{ok:true}`；不存在 404。
- `POST /api/teardowns/{id}/to-idea` body `{expand?: true, notes?: ≤500}` → 同 v0.9.2 `from-seed`：`expand=false` 同步 `{idea}`，`expand=true` Job（`kind=idea_seed`）。种子来自拆书产物（卖点、金手指机制、开篇），`source.type="teardown"`、`source.ref="teardown#<id>"`、`source.teardown_id`。
- `POST /api/teardowns/{id}/to-bible` body `{book_id, parts: ["characters"|"golden_finger"|"reusable"|"selling_points", ...]}`（同步，不调模型）→ `{cards: [Card], warnings: string[], skipped: int}`。人设模板 → character 条目（name 用「模板·<role>」，summary 为模板描述）；金手指 → power 条目；可复用套路 / 卖点 → world 条目（`data.kind` 区分）。所有条目 `data.from_teardown=<id>`、`data.draft=true`。写前存设定快照；与原文指纹做 8 字 n-gram 比对，过相似的跳过（计 `skipped` 与 warnings）。书不存在 404，parts 空或含未知值 422。

### 版本
- `GET /api/health` → `version: "0.9.3"`。


### v0.9.3 实现与契约的偏离（2026-11-17 补）
- 审批模式默认值：未显式设置过的书，`approval_mode` 按 `agent_auto_apply` 映射显示，但章节 AI 维持旧行为；只有显式设为 `review`（`approval_mode_explicit=true`）才拦截章节 AI 落库。
- `thicken` 在 review 模式下，正文对比稿放在 `draft.before/after`（原有 `before/after` 是指标）。
- `/api/estimate` 的 `kind` 另支持 `aigc`：返回 0 token、`calls_est=1`、`route=model="zhuque"`，note 说明计朱雀检测额度。
- 完整度「主角五维」项的 job 只出建议不写库；前端改为跳设定库自动补全，采纳后才算完成。


## v0.10 同人创作（原著资料、版权确认、同人书三档遵循度、12 方向、OOC 检查、原著重合）

> 前端按本节对接。调模型的接口（原著卡提炼、OOC 检查）返回 Job（`{id, job_id, kind, status, ...}`），结果在 `Job.result`，用 `/api/jobs/{id}`（或 SSE）轮询。其余同步。版本号本次不改。
> 原则：**原著原文不入库**。导入的文本只在任务内存里用一次，库里只存提炼出的「原著设定卡」与所取片段的 8 字 crc32 指纹（与 v0.9.3 拆书同一算法，不可还原原文）。

### 数据形状

**SourceCards**（原著设定卡）
```json
{
  "characters": [{"name": "", "aliases": [""], "role": "主角|主要配角|反派|…", "personality": "≤160", "speech_style": "≤100",
                  "catchphrases": ["≤30，最多 6"], "relations": [{"target": "", "relation": ""}],
                  "abilities": [""], "limits": [""], "notes": ""}],
  "world": {"summary": "≤400", "rules": ["≤80，最多 12"], "locations": [{"name": "", "desc": ""}]},
  "factions": [{"name": "", "stance": "", "members": [""], "notes": ""}],
  "timeline": [{"order": 1, "event": "≤80", "characters": [""], "impact": ""}],
  "scenes": [{"title": "", "summary": "≤160（名场面，用自己的话）", "characters": [""]}]
}
```
角色最多 30、时间线最多 60、名场面最多 30。除口癖与名字外，任何字段和原文有连续 8 字相同：提炼时清空字段/删掉条目并记 `warnings`；作者 PUT 手改时只提醒不删。

**FanficSourceBrief**：`{id, title, source: "paste"|"txt", chars（实际取用字数）, total_chars（导入总字数）, depth: "quick"|"standard"|"deep", focus: string[], completeness: 0–100, counts: {characters, factions, timeline, scenes}, warnings_count, used_by: [book_id], model, created_at, updated_at}`
**FanficSource** = Brief + `{cards: SourceCards, warnings: string[]}`

**Book.fanfic**（`book_out` 新字段 `fanfic`，原创书为 `null`）
```json
{"source_id": 1, "source_title": "", "fidelity": "strict|moderate|loose", "direction": "canon_fill|…",
 "extra_source_ids": [2], "notes": "", "copyright_ack": true, "copyright_ack_at": "ISO", "attached_at": "ISO"}
```

### 方向模板 / 遵循度 / 版权声明
- `GET /api/fanfic/directions` →
  `{directions: [{id, label, desc, tips: string[], risks: string[], suggested_fidelity, template}], fidelities: [{id, label, desc, pass_score}], copyright_notice: string}`
  - 12 个方向 id：`canon_fill` 原著向补完、`if_line` if 线改写、`transmigration` 穿书、`rebirth` 重生、`system` 系统、`au_modern` AU 现代、`au_ancient` AU 古代、`side_pov` 配角主视角、`cp` CP 向、`villain_redemption` 反派洗白、`epilogue` 后日谈、`crossover` 跨作品联动。`template` 是可以填进「创作想法」输入框的结构化提示。
  - 遵循度：`strict` 严格遵循（原著设定与时间线都不改，OOC 通过线 80）/ `moderate` 有据延展（可改支线与结局、人设不变，70）/ `loose` 分歧世界 AU（只保留人物核心，55）。
  - 前端在建同人书前展示 `copyright_notice` 并要求勾选。

### 原著资料
- `POST /api/fanfic/sources` → Job（`kind=fanfic_source`）。两种请求体：
  - JSON：`{source: "paste"|"txt", text: string, title?: ≤60, focus?: string[≤10]（重点角色名/剧情关键词）, depth?: "quick"|"standard"(默认)|"deep"}`
  - multipart/form-data：`file`（TXT，UTF-8/GBK/UTF-16 自动识别）、`title?`、`focus?`（逗号分隔）、`depth?`
  - 上限 30MB（超出 413）；少于 200 字 400；source/depth 非法 422。
  - 只取需要的部分：原文 ≤20 万字全取；更长时按「focus 段落（≤45%）→ 开头连续（35%）→ 后文均匀抽样」取满 20 万字。depth 决定提炼轮数（1/2/4 轮，每轮 ≤12000 字），多轮结果按角色名/别称合并。
  - `Job.result = {source: FanficSource, source_id}`。
- `GET /api/fanfic/sources` → `FanficSourceBrief[]`（新的在前，不含 cards）。
- `GET /api/fanfic/sources/{id}` → FanficSource；不存在 404。
- `PUT /api/fanfic/sources/{id}` body `{title?, cards?: {characters?|world?|factions?|timeline?|scenes?}}`（给了哪块就整块替换哪块）→ `{source: FanficSource, warnings: string[]}`；cards 含未知键 422。
- `DELETE /api/fanfic/sources/{id}?force=false` → `{ok: true}`；有同人书在用时 409（加 `force=true` 强删，书上的 fanfic 保留，上下文改为只按规则把握，`GET /books/{id}/fanfic` 的 `source_missing=true`）。

### 同人书
- 建书时指定：`POST /api/books` body 增加 `fanfic?: {source_id, fidelity?: "moderate", direction?: "canon_fill", extra_source_ids?: int[≤9], notes?: ≤1000}`、`copyright_ack?: bool`。
  给了 `fanfic` 但 `copyright_ack !== true` → **400**（不建书）；source 不存在 404；fidelity/direction 非法 422。
- `POST /api/books/{id}/fanfic` body `{source_id, fidelity?, direction?, extra_source_ids?, notes?, copyright_ack: true}` → `FanficInfo`。把已有书设为同人书或整体重设；同样必须 `copyright_ack: true`（否则 400），每次都刷新 `copyright_ack_at`。
- `GET /api/books/{id}/fanfic` → `FanficInfo = {book_id, fanfic: null | {...Book.fanfic, direction_label, fidelity_label, source: FanficSourceBrief|null, source_missing: bool}}`
- `PATCH /api/books/{id}/fanfic` body `{fidelity?, direction?, extra_source_ids?, notes?}` → FanficInfo（改档不必重新确认版权）；非同人书 400。
- `DELETE /api/books/{id}/fanfic` → `{ok: true}`（变回原创书，`book.fanfic=null`）。
- `GET /api/books/{id}/fanfic/context` → `{book_id, text, chars}`：写章/大纲时注入的同人上下文原文（预览用；原创书 `text=""`）。
- `POST /api/books/{id}/fanfic/import-cards` body `{parts?: ["characters"|"factions"|"world"|"locations"]}`（默认 characters，同步）→ `{cards: [Card], skipped: int}`。原著角色 → character 条目（`data.voice/catchphrases/abilities/limits/relations/aliases/canon_role`，`data.role` 按 主角→protagonist、反派→antagonist、其余 ally），势力 → faction，世界观 → world「原著世界观」，地点 → location；`data.from_fanfic_source=<id>`；写前存设定快照；重名跳过。非同人书 400。

**上下文注入**：同人书的所有「书设定」上下文（大纲、扩写、章纲、写章前缀、设定 AI、包装等，凡用 `book_context` 的提示词）末尾自动附「【同人创作·原著设定】」块：遵循规则 + 方向要点 + 作者补充 + 原著角色（性格/说话/口癖；strict/moderate 另带关系/能力/边界）+ 世界观与势力（loose 不带）+ 时间线（strict：「已发生，不得改写」全量；moderate：主线节点「支线与结局可改」；loose 不带）+ 联动原著角色。上限约 2400 字。

### 章节检查
- `POST /api/chapters/{id}/ooc-check` → Job（`kind=fanfic_ooc`，`book_id` 为章节所在书）。非同人书 / 原著已删 / 没正文 400，章节不存在 404。
  `Job.result = {chapter_id, ooc: OocResult, overlap: Overlap}`，同时存进章节 `fanfic_meta`。
  ```json
  OocResult = {"fidelity": "strict", "fidelity_label": "", "pass_score": 80, "overall": 0-100, "verdict": "pass|warn|fail",
    "characters": [{"name": "", "score": 0-100, "model_score": 0-100|null, "level": "pass|warn|fail", "verdict": "",
                    "issues": [{"type": "speech|catchphrase|relation|ability|timeline", "type_label": "言行|口癖|关系|能力越界|时间线",
                                "severity": "high|mid|low", "quote": "本章原句", "problem": "", "suggestion": "", "source": "model|program"}]}],
    "summary": "", "ignored_issues": 0, "content_hash": "", "checked_at": "ISO", "model": ""}
  ```
  - 只检查原著卡里、且名字/别称在本章出现的角色；模型给的 quote 必须原样出现在正文里，否则丢弃。
  - 宽严：strict 不忽略任何类型，relation/ability/timeline 的 low 升为 mid，扣分系数 1.3；moderate 忽略 timeline，系数 1.0；loose 忽略 timeline/ability/relation，非 speech 的 high 降为 mid，系数 0.7。被忽略的计入 `ignored_issues`。
  - 分数 = (模型分 + 程序分) / 2，程序分 = 100 − Σ(high 25 / mid 10 / low 3)×系数；`level`：≥通过线且无 high 为 pass，≥通过线−15 为 warn，否则 fail；`verdict` 取最差。
  - 程序另查口癖刷屏：同一口癖一章出现超过 3 次 → `catchphrase/low`（`source="program"`）。
- `GET /api/chapters/{id}/ooc` → `{chapter_id, ooc: OocResult & {stale: bool} | null, overlap: Overlap & {stale: bool} | null}`（`stale`=正文已改过）。
- `POST /api/chapters/{id}/fanfic-overlap`（同步，不调模型，结果也存进 `fanfic_meta.overlap`）→ `{chapter_id, overlap: Overlap}`。
  ```json
  Overlap = {"ngram": 8, "hits": 0, "segments": 0, "longest": 0, "ratio": 0.0, "level": "ok|info|warn|high", "warning": "",
             "samples": ["本章里与原著重合的片段（≤60 字，最多 5 条，按长度降序）"], "content_hash": "", "checked_at": "ISO"}
  ```
  去空白和标点后逐 8 字比对原著指纹（主原著 + 联动原著）；口癖与角色名不计入。`level`：无重合 ok；占比 <1% 且最长 <20 字 info；占比 <5% warn；否则 high。
- 章节 `fanfic_meta`（新列，`chapter_out` 暂不输出，用上面的 GET 取）：`{ooc?: OocResult, overlap?: Overlap}`。

### 审稿/写章接入点（后端内部，前端无感）
- `app.services.fanfic.ooc_block(session, chapter, content=None) -> list[issue]`：审稿格式的 issues（`{severity, dimension: "character"|"semantics", quote, comment}`），来源为已存且未过期的 OOC 结果、口癖刷屏、原著重合 warn/high；原创书返回 `[]`。审稿合并进 `review.issues` 即可（尚未接入）。
- `app.services.fanfic.text_overlap(book_id, text) -> Overlap`：写章/改写后可调，用于生成 warnings（尚未接入）。

## v0.9.4 提交前修中等问题、数值一致性、补丁后重审、任务断点续跑、lint 阈值校准

### 写作开关
- `GET /api/settings/writing` 新增字段：`fix_mid_before_commit: bool = true`、`auto_rereview: bool = true`；`PUT /api/settings/writing` 同名字段可选。
- `GET /api/books/{id}/writing-settings` → `{book_id, overrides: {fix_mid_before_commit: bool|null, auto_rereview: bool|null}, effective: {...}, global: {...}}`（`null` = 跟随全局）；书不存在 404。
- `PUT /api/books/{id}/writing-settings` body `{fix_mid_before_commit?: bool|null, auto_rereview?: bool|null}`（只改出现的字段，传 `null` 恢复跟随全局）→ 同 GET。

### 提交前修中等问题
- 触发：`POST /api/chapters/{id}/commit` 与写章流程的自动提交，在生成摘要之前。条件：生效的 `fix_mid_before_commit=true`，最后一轮审稿 `review.issues` 里有 `severity=mid` 且 `dimension ∈ {continuity, retention}`、quote 仍在正文里的问题。
- 做法：先应用对应这些问题、未应用过的审稿补丁（逐字匹配）；剩下没被补丁覆盖的，按问题描述定点改写被点名的原句（模型调用 task=`humanize`）。每章只做一次；改过就把旧正文压进历史（标签「提交前修中等问题前」，可 `/undo`），重跑 lint，不重新审稿。审批模式 `review` 时不改正文，只记录 `skipped`。
- 记录：`review.pre_commit_fix = {issues: [issue 下标], patches_applied: [补丁下标], patches_skipped: [{index, reason}], rewritten: int, changed: bool, at, skipped?: string}`；`changes.warnings` 追加说明。写章 Job 的 `result.pre_commit_fix` 同上（提交时才有）。

### 审稿补丁后自动重审
- 写章流程：`auto_apply_review_patches` 应用了 ≥1 个补丁、且生效的 `auto_rereview=true` → 再审一次（只 1 次）。`Job.result.rereview = {round: 1, at, before_overall, after_overall, passed, high_left, dropped_issues}`。
- 新审稿写回章节：`review.rereview` 同上；`review.patches` = 旧补丁（下标不变，`issue_ref=null`，`round: 0`，未应用的带 `stale: true`）+ 新补丁（`round: 1`，下标接在后面）；`review.patch_log` 保留。`stale` 补丁手动应用时跳过（reason「补丁来自上一轮审稿，已过期」）。
- 重审仍有 high：`review.passed=false`、`review.flagged=true`、`review.flag_reason`，`changes.warnings` 追加；章节不提交，`Job.result.reason` 说明「已标记」。
- `review_out` 新增：`rereview: object|null`、`flagged: bool`、`flag_reason: string`、`pre_commit_fix: object|null`。

### 数值一致性（lint + 审稿）
- `Lint` 新增 `numeric_conflicts: NumericIssue[]`、`lint_tier: "fanqie"|"publish"`；有问题时 `warnings` 追加「数值不一致：…」（最多 5 条）。
- 同样的问题进 `review.issues`（和程序检查一起计分）：
  ```json
  NumericIssue = {"severity": "mid", "dimension": "continuity", "quote": "本章原句", "comment": "叶承的年龄前后不一致：前面写「十七岁」，这里写「十八岁」，统一成一个数",
    "position": {"offset": 0, "paragraph": 0, "match": "十八岁"}, "source": "lint:numeric", "object": "叶承",
    "kind": "weight|height|length|width|thick|depth|range|power|speed|age|days|realm",
    "related": {"quote": "", "offset": 0, "paragraph": 0} | {"source": "ledger", "label": "事实账本·境界（第3章起）", "value": "炼气五层"}}
  ```
  `offset` 为正文字符下标，`paragraph` 为非空段落序号（从 0 开始）。对照来源：本章之前仍有效的 `facts` + 设定卡 `data` 里的 age/年龄/身高/体重/境界/修为/高度/重量/功率/时速/长度。本章写了“突破/晋升/踏入…”时境界不报；期限中间写到“第二天/次日/一夜过去…”时不报。

### 任务断点续跑
- `Job.status` 新增取值 `interrupted`（服务重启时有断点、且 kind 支持续跑的任务；目前只有 `chapter_write_next`）。SSE `/jobs/{id}/events` 在 `interrupted` 时结束。
- `GET /api/jobs/{id}` 新增 `resumable: bool`、`checkpoint: null | {stage, resumes, updated_at, chapter_id, number, scenes_total, scenes_done, variants_done}`。`stage` 取值：`node`、`scenes`、`scene:{版本}:{已写场景}/{场景总数}`、`variant:{n}`、`chapter`、`adopted`、`refined`、`patched`。`resumable` = 状态为 interrupted 或 failed、有断点、kind 支持续跑。
- `POST /api/jobs/{id}/resume` → Job（同一个 id，状态回到 queued，`message` 写明从哪一步之后继续），带 `resumable`/`checkpoint`。不可续跑 409（状态不对 / 不支持 / 没断点），任务不存在 404。续跑跳过已完成的步骤：已拆好的场景不重拆，已写完的场景不重写，已建章则从采纳/精修/补丁/提交继续。任务成功后断点删除。
- 批量写章（`chapter_write_batch`）与 Agent 发起的写章暂不存断点（重启后仍为 failed）。
- 新表 `job_checkpoint(job_id PK, kind, book_id, stage, state JSON, resumes, updated_at)`。

### lint 阈值档
- 阈值集中在后端配置 `Settings.lint_profiles`（`fanqie` 番茄档、`publish` 出版档）与 `lint_platform_map`（fanqie→fanqie，qidian/generic→publish）；环境变量 `NOVELOS_LINT_PROFILES` 可整体覆盖。
- 番茄档长段：>100 字（原 70），且长段 ≥3 段、占全章段落 ≥10% 才计问题、出警告并点名最多 3 段定点修；`Lint.long_paragraphs` 仍是 >100 字段落数。校准记录见 `docs/research/lint-calibration-v094.md`。
