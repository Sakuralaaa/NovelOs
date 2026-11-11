# NovelOS v0.1 API 合约（前后端共同遵守）

后端：FastAPI，前缀 `/api`，JSON，UTF-8。时间 ISO8601。ID 为整数。
长任务（生成类）统一返回 `Job`，前端轮询 `GET /api/jobs/{id}`（或订阅 SSE `GET /api/jobs/{id}/events`，可选）。

## 通用
- `GET /api/health` → `{status:"ok", version}`
- 错误：`{detail: string}`，HTTP 4xx/5xx。

## Job
```
Job { id, kind: string, status: "queued"|"running"|"succeeded"|"failed", progress: 0-100, message: string,
      result: object|null, error: string|null, book_id: int|null, created_at, updated_at }
```
- `GET /api/jobs?book_id=` → Job[]（最新在前，最多 50）
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
ChangeSet { new_entities[], state_changes[], foreshadow: [{action:"plant"|"advance"|"resolve", id|null, desc}] }
```
- `GET /api/books/{id}/chapters` → Chapter[]（不含 content）
- `GET /api/chapters/{id}` → Chapter
- `PUT /api/chapters/{id}` (title, content) → Chapter（人工修改）
- `POST /api/books/{id}/chapters/write-next` → Job（取下一章细纲 → 写 → 检查 → 审稿 → 人味 lint → 定点重写 → 提交；result: {chapter_id}）
- `POST /api/books/{id}/chapters/write-batch` (count ≤ 10) → Job
- `POST /api/chapters/{id}/review` → Job；`POST /api/chapters/{id}/humanize` → Job；`POST /api/chapters/{id}/commit` → Chapter

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
