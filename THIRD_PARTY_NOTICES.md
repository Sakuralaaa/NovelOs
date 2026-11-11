# 第三方声明（THIRD_PARTY_NOTICES）

NovelOS 以 Apache-2.0 发布。写作技能层（`backend/app/skills/rules/*.md`）与 AI 腔词表（`backend/app/lint/banned_zh.py`）
参考了下列开源项目。规则正文由本项目用自己的话重写；**仅 MIT / Apache-2.0 / CC BY 来源**有少量规则表述被改写复用，并在此署名。
无协议、GPL、AGPL 来源只借鉴思路，没有复制其文本或代码。每个规则包文件头部的 `sources` 元数据标明了具体来源与使用方式
（`adapted` = 改写复用；`idea-only` = 只借思路）。

## 一、改写复用文本的来源（MIT / Apache-2.0 / CC BY）

### chengzhi-c/natural-talk — MIT
- 仓库：https://github.com/chengzhi-c/natural-talk
- 使用：`SKILL.md`（第 7 条叙述破折号、第 12 条翻译腔、第 15 条装饰性喻体）与 `references/fiction.md`（B1 翻案腔、B2 叙述破折号、
  B3 比喻、B4 修饰副词、B5 正向置换、B6 舞台剧抽搐、B7 假深沉、B8 对白节奏、B9 计数癖、“人动景才出”等叙事工法、清理边界）
  的规则要点被改写并入 `writing.md`、`humanize.md`；`banned_zh.py` 中“翻案腔 / 叙述破折号 / 修饰副词+动作 / 翻译腔 /
  舞台剧抽搐 / 装饰对白标签 / 陈腐比喻 / 预告式套话”几类及其部分词条取自该项目。

```
MIT License

Copyright (c) 2026 Natural Talk Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### 其他 MIT 来源（版权归各仓库作者所有，许可文本同上 MIT 模板）
| 仓库 | 用在哪里 |
|---|---|
| zenstory-ai/oh-story-claudecode | 主角 300 字内出场、1000 字内钩子、章尾钩子；JSON 唯一底账思路 |
| PenglongHuang/chinese-novelist-skill | 每章写前分析 → 写 → 润色 → 更新摘要的流程 |
| op7418/Humanizer-zh | AI 腔模式类别（不是X而是Y、三段式、意义拔高等） |
| wei125775-lab/deai | 词表与脚本同源维护；“仿佛/一丝/一抹/几分”出现即处理 |
| dbhosbu-dotcom/renwei（profiles/fiction） | 对话同质化、情绪直述、陈腐身体反应、副词过载等 fiction 模式 |
| deedeekong07-alt/fiction-humanizer-zh | 场景六定（功能、目标、压力、失败点、转折、余波）；每 300–500 字压力变化 |
| KKKKhazix/human-writing（references/fiction.md） | 每场戏至少改变一项（信息、关系、计划、风险、权力、情绪） |
| tance-mang/chinese-webnovel-skills | 打脸四拍；300 字内引爆冲突；每 10 万字卷级大爆点 |
| LAY-lgtm/novel-writing-framework | 单章阻断五问；3/5/10 爽点节奏；章末四种钩子；每 3 章扫 AI 指纹 |
| xiaofeng-928/chinese-longnovel-skill | 黄金三章微操；前三章禁止长独白/大段世界观；金手指写输入、成本、限制；伏笔回收距离 |
| huahuakandaima/human-novel-writer | 开篇承诺四要素；角色入场门禁（知道/不知道/误解）；语言指纹 |
| wei125775-lab/novel-writing-skills（save-the-cat-novel） | 15 拍与 5 个基础动点；一句话简介压力测试 |
| Nanako0129/sepia | 主题不让叙述者点明；Echo test |
| danjdewhurst/story-skills | 场景结果 yes / no / yes-but / no-and，连续 3 个 yes 报警；卷目标与每章戏剧问题 |
| evelynyaxueke/anti-ai-writing-kit-zh | 起稿即加载规则的思路（仅思路） |
| WindXRan/fanqie-radar | 榜单题材聚合、请求间隔与 UA 的做法（仅思路，代码自写） |

### Apache-2.0
| 仓库 | 用在哪里 |
|---|---|
| xwcai999/opencreator-novel | 章节控制卡字段、待兑现项状态、相邻章不并行、同一根因最多修两轮 |
| voocel/ainovel-cli | 确定性调度引擎、卷/弧滚动规划（仅思路，代码自写） |
| wfcz10086 系项目（证据式审稿） | 审稿必须引原句、分数由程序计算（仅思路，代码自写） |

### CC BY 4.0（文档）
| 仓库 | 用在哪里 |
|---|---|
| MintoTsukino/claude-novel-workflow | 三层审稿、变量“饥饿”检查的思路（署名：MintoTsukino） |

## 二、只借思路、未复制任何文本或代码的来源
- 无协议：Tomsawyerhu/Chinese-WebNovel-Skill（章末计划四问、章末四层诊断）、304769384-png/fanqie-novel-skill（对话占比档位、话疗检查）、
  jiaw-Zh/long-novel-writer（冻结式分层摘要、facts 只追加、known_by）、Distilled-Novel-Toolbox。
- GPL-3.0：lingfengQAQ/webnovel-writer（审过才提交）、aby-aby111/fanqie-short-story.skill（书名四维打分思路，评分代码自写）。
- AGPL-3.0：Hurricane0698/novelwriter（续写时只注入当前章相关设定；生成结果先是草稿，确认后才进底账）、inkos、NovelForge 等。
- 有商用限制、未使用：orange2ai/renwei-writing。

## 三、运行时依赖
FastAPI（MIT）、Starlette（BSD-3）、SQLModel（MIT）、SQLAlchemy（MIT）、Pydantic（MIT）、pydantic-settings（MIT）、
httpx（BSD-3）、cryptography（Apache-2.0 / BSD）、Pillow（MIT-CMU）、uvicorn（BSD-3）。Docker 镜像内的文泉驿微米黑字体为 GPLv3 + 字体例外 / Apache-2.0 双许可。
