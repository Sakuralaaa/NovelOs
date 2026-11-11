---
stage: bible
title: 设定库规则
version: 0.1
sources:
  - huahuakandaima/human-novel-writer | MIT | adapted
  - xiaofeng-928/chinese-longnovel-skill | MIT | adapted
  - jiaw-Zh/long-novel-writer | 无协议 | idea-only
  - zenstory-ai/oh-story-claudecode | MIT | idea-only
  - chengzhi-c/natural-talk | MIT | adapted
---
# 设定库规则

1. 设定先结构后文字：world / power / faction / character / item / location 六类卡片，每张卡有 name、summary、data。
2. 金手指（power）必须写清三项：怎么用（输入）、用了付出什么（成本）、什么情况下用不了（限制）。没有成本和限制的金手指会让爽点贬值。
3. 人物卡入场门禁：写明此刻知道什么、不知道什么、误解什么（data.knows / data.unknown / data.misbelief），以及 known_by（哪些角色知道这张卡上的秘密）。
4. 人物卡说话方式（data 约定键）：voice（说话方式，句长、语气词、称呼习惯）、catchphrases[]（口头禅，1–3 个，克制使用）、habits[]（小动作，具体到身体部位）、demeanor（神态习惯）。不同角色隐去名字后要能分辨谁在说话。
5. 事实分“作者真相”和“读者已知”两条线（visibility = author / reader）。事实只追加，变化时关闭旧事实、写新事实，不改写历史。
6. 主角、主要对手、关键配角至少各一张卡；地点卡写感官锚点（气味、温度、声响、材质），供正文“人动景才出”时取用。
