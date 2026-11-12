# NovelOS：AI 网文全流程工作台（番茄向）

从“看榜选题”到“导出发布包”一条龙：热点雷达 → 选题 → 设定库 → 大纲/细纲 → 场景化写正文 → 证据式审稿 → 人味检查与精修 → 书名简介封面 → 导出。
单用户、自托管，数据都在你自己的机器上。

> 协议：Apache-2.0（见 `LICENSE`）。参考的开源写作规则及其署名见 `THIRD_PARTY_NOTICES.md`。

---

## 一条命令部署（推荐）

准备一台装了 Docker 的电脑或服务器（Windows/macOS 装 Docker Desktop；Linux 服务器见下面的安装提示），然后：

```bash
git clone <你的仓库地址> novelos
cd novelos
bash deploy.sh
```

脚本会自动：检查 Docker → 生成 `.env`（带随机加密密钥）→ 构建并启动 → 等到服务就绪后打印访问地址。
看到“部署完成！”后，用浏览器打开 `http://服务器IP:8080` 即可。

没装 Docker？Linux 服务器执行：`curl -fsSL https://get.docker.com | sudo sh`，再 `sudo systemctl enable --now docker`。

不想用脚本，也可以手动：

```bash
cp .env.example .env        # 按需修改端口、填一个随机的 NOVELOS_SECRET
docker compose up -d --build
```

## 第一次打开要做什么

1. **去“设置”页添加模型渠道**：填名称、`base_url`（填到 `/v1` 为止，例如 `https://api.openai.com/v1`，或你自己的 new-api / one-api 网关地址）、API Key、模型名。
   Key 会加密后保存，页面上只显示掩码。
2. **按任务分配模型（路由）**：规划（planner）、正文（writer）、审稿（reviewer）、嵌入（embedding）、生图（image）可以分别选不同的模型。
   某个渠道调用失败会自动重试 2 次，再切到其他渠道。生图不配置时，封面用本地生成的渐变图。
3. 回到首页，从“热点雷达”或“新建作品”开始。

### 访问密码

面板默认开启登录，打开任何页面都会先看到登录页，接口和封面图片在未登录时一律返回 401。

- **初始密码**：首次启动自动生成，`deploy.sh` 结束时会打印出来，也保存在 `./data/initial_password.txt`。登录后到「设置 → 账户安全」修改，改完该文件自动删除，其他设备的登录同时失效。
- **固定密码**：在 `.env` 里填 `NOVELOS_PASSWORD=你的密码`（至少 8 位）后重启，以它为准。
- **安全机制**：密码只存 PBKDF2 加盐哈希；会话是签名的 HttpOnly Cookie（勾选“30 天内保持登录”为 30 天，否则 12 小时）；同一 IP 15 分钟内输错 5 次锁定 15 分钟；写操作校验来源防 CSRF。
- **公网部署**：务必套 HTTPS（Caddy / Nginx），并设置 `NOVELOS_COOKIE_SECURE=true`。反向代理需要转发 `X-Forwarded-For` / `X-Forwarded-Proto`。
- **忘记密码**：删除 `./data/auth.json` 后重启，会重新生成初始密码。
- 脚本调用 API 可用 `Authorization: Basic base64(任意用户名:密码)`。`/api/health` 无需登录。

### 演示（mock）模式

一个渠道都没配时，系统自动进入 **mock 模式**：所有生成都用内置的确定性假数据（像样的中文示例内容），
可以把“选题 → 设定 → 大纲 → 写章 → 审稿 → 精修 → 包装 → 封面 → 导出”整条流程完整走一遍，方便先熟悉操作。
mock 内容只用于演示，不要拿去发布。配好任意一个启用的渠道后自动退出 mock 模式。

## 写作流程里系统替你做了什么

- **没细纲不写正文**：写下一章时先取章细纲，没有就按“滚动规划”自动展开下一弧。
- **场景化写作**：每章先拆成 3–6 个场景节拍（目标、冲突、结果、在场人物、感官锚点），再逐场景写，避免“对着大纲扩写”。
- **只给相关设定**：每章只把细纲点名的人物、地点、物品、相关伏笔放进上下文，人物按卡片里的说话方式、口头禅、小动作写。
- **风格卡**：粘贴一段你喜欢的范文（≤5000 字），系统统计句长、对话比例、描写密度，并截取 800–1500 字作为写法示范。
- **证据式审稿**：审稿意见必须引用正文原句，引不出原句的意见会被丢弃；分数由程序计算。
- **人味检查（纯代码）**：AI 腔词表（80+ 条）、全书重复短语、对话占比、句长、短句比例、裸对白、概述句、翻案腔、叙述破折号、翻译腔等。
  阈值是经验值，尚未用番茄人写作品校准。
- **定点修改**：超标时只改被点名的句子或段落（最多 1 轮）；“描写增厚”只改裸对白和概述段落，不新增情节。
- **多版本**：可一次写 2–3 个版本供挑选，也可在设置里开启“自动采纳最高分”。
- **草稿不进底账**：章节在“提交”前只是草稿；提交时章节、事实、伏笔、摘要、新人物一次性写入。

## ⚠️ 合规提示（务必阅读）

- **发布时如实勾选 AI 申报。** 番茄发布章节时会询问是否使用 AI，请如实勾选；《人工智能生成合成内容标识办法》要求发布者主动声明 AI 生成内容。
- **人工改写把关。** 平台持续整治“滥用 AI 批量生成、缺乏原创性”的内容（拒签、限流、下架、封号）。请逐章通读修改，控制更新量，不要批量开书。
- **NovelOS 不会自动登录或发布到作者后台。** 导出的发布包（建书资料、分章 txt、封面、AI 申报提示）请你手动上架。
- **热点雷达默认关闭**，只用演示数据（男频 27 本 + 女频 23 本，每天换一批）。开启后每天抓取一次番茄网页版「阅读榜」：男频 19 个、女频 18 个题材榜，每榜默认前 30 本（`NOVELOS_RADAR_PER_BOARD` 可调到 100），带名次升降；同一天的榜单版本只入库一次。请求间隔 ≥1 秒。番茄用户协议禁止爬虫和自动化接入，
  开启即表示你了解这一风险，并仅用于个人选题参考；随时可在雷达页关闭。

---

## 常用运维

以下命令都在 `novelos/` 目录里执行（老版本 Docker 把 `docker compose` 换成 `docker-compose`）。

| 要做什么 | 命令 |
|---|---|
| 查看状态 | `docker compose ps`（STATUS 显示 `healthy` 即正常） |
| 看日志 | `docker compose logs -f novelos`（`Ctrl+C` 退出） |
| 重启 | `docker compose restart novelos` |
| 停止 | `docker compose down`（数据在 `./data`，不会丢） |
| 升级 | `git pull` 然后重新运行 `bash deploy.sh` |

### 备份与恢复（数据都在 `./data`）

`./data` 里有：`novelos.db`（全部作品与设置）、`media/`（封面图片）、`secret.key`（未设置 `NOVELOS_SECRET` 时自动生成的密钥）。

```bash
# 备份（服务运行中也可以，用 SQLite 在线备份，保证一致性）
mkdir -p backups
docker exec novelos python -c "import sqlite3; s=sqlite3.connect('/data/novelos.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close()"
mv data/backup.db "backups/novelos-$(date +%Y%m%d-%H%M).db"
tar czf "backups/media-$(date +%Y%m%d).tgz" data/media data/secret.key 2>/dev/null || true
cp .env backups/   # .env 里的 NOVELOS_SECRET 也要备份，否则恢复后模型 Key 无法解密

# 恢复
docker compose down
cp backups/novelos-20261112-0800.db data/novelos.db     # 换成你的备份文件名
rm -f data/novelos.db-wal data/novelos.db-shm
tar xzf backups/media-20261112.tgz                       # 如有需要
docker compose up -d
```

### 排障清单

- **端口冲突**（日志里有 `address already in use` / 打不开）：编辑 `.env`，把 `APP_PORT=8080` 改成别的（如 `8090`），再 `bash deploy.sh`。
  `docker-compose.yml` 里的端口写法是 `${APP_PORT:-8080}:8000`，只需要改 `.env`。
- **云服务器外网打不开**：在云厂商控制台的安全组/防火墙放行该端口；本机防火墙：`sudo ufw allow 8080`。
- **构建很慢或失败**：多为网络问题（拉取 node / python 镜像、npm、pip 依赖）。可配置 Docker 镜像加速后重试。
- **一直是演示（mock）模式**：设置页至少要有一个“启用”的渠道；点渠道的“测试”看返回的错误信息。
- **生成失败提示“所有渠道均失败”**：检查 base_url 是否填到 `/v1`、Key 是否有效、模型名是否正确、余额是否充足。
- **提示 Key 解密失败**：`NOVELOS_SECRET` 被改过或丢了。改回原值，或在设置页重新填写各渠道的 Key。
- **任务一直不动**：服务重启会把进行中的任务标记为失败，重新点一次即可。
- **封面上没有书名文字**：本地开发环境缺中文字体；Docker 镜像已内置文泉驿微米黑，或设置 `NOVELOS_FONT_PATH` 指向一个中文字体文件。

---

## 本地开发

```bash
# 后端（http://127.0.0.1:8000）
cd backend && bash scripts/dev.sh
# 测试
cd backend && pip install -r requirements-dev.txt && python -m pytest
# 前端（http://localhost:5173，已允许跨域）
cd frontend && npm install && npm run dev
```

后端结构：`app/api`（路由）、`app/models`（表）、`app/services`（流水线与业务）、`app/llm`（网关与 mock）、`app/lint`（人味检查）、
`app/radar`（雷达）、`app/skills`（写作规则包与提示词）、`app/jobs`（后台任务）。接口约定见 `docs/API_CONTRACT.md`。

常用环境变量：`NOVELOS_DATA_DIR`（数据目录，默认 `./data`，镜像内为 `/data`）、`NOVELOS_SECRET`、`NOVELOS_STATIC_DIR`（前端构建产物目录，默认 `/app/static`）、
`NOVELOS_FONT_PATH`、`NOVELOS_DISABLE_SCHEDULER`。

## 协议

Apache License 2.0。第三方署名见 `THIRD_PARTY_NOTICES.md`。

## 预构建镜像

每次推送 `v*` tag，GitHub Actions 会构建 `linux/amd64` 和 `linux/arm64` 双架构镜像并发布到 GHCR：

```bash
docker pull ghcr.io/sakuralaaa/novelos:latest
docker run -d --name novelos -p 8000:8000 -v novelos-data:/data \
  -e NOVELOS_PASSWORD=你的密码 ghcr.io/sakuralaaa/novelos:latest
```

在 `docker-compose.yml` 里把 `build: .` 换成 `image: ghcr.io/sakuralaaa/novelos:latest` 即可直接拉取。
