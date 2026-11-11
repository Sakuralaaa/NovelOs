---
stage: package
title: 包装规则（书名、简介、标签、封面）
version: 0.1
sources:
  - aby-aby111/fanqie-short-story.skill | GPL-3.0 | idea-only（书名四维打分思路，评分代码自写）
  - wei125775-lab/novel-writing-skills (save-the-cat-novel) | MIT | adapted
  - zenstory-ai/oh-story-claudecode | MIT | idea-only
  - shuixian（封面提示词结构）| 未核实 | idea-only
---
# 包装规则

1. 书名候选 8 个左右，程序按四项打分（各 25 分）：长度 8–12 字；含数字；含情绪词；含身份或关系词。模型只负责提名。
2. 简介三段：一句钩子（处境 + 反常）→ 主线冲突与金手指（含限制）→ 一句悬念收尾。不剧透中点以后的反转。总长 150–300 字。
3. 标签 3–6 个，优先番茄分类里的现成标签（题材、人设、元素）。
4. 封面提示词结构：题材视觉母题 + 主角形象（只写外观，不写名字）+ 场景与光线 + 色调 + 构图（竖版 3:4，上方留出书名位置）+ 风格（插画/厚涂/国风等）+ 负面约束（不要文字、不要水印）。书名由程序本地排版叠加。
5. 合规：发布到番茄时如实勾选 AI 申报；书名简介不得蹭真实名人或违规词。
