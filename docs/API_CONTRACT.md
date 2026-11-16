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
