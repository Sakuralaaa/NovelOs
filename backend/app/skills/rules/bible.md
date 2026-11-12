---
stage: bible
title: 设定库规则
version: 0.2
sources:
  - huahuakandaima/human-novel-writer | MIT | adapted
  - xiaofeng-928/chinese-longnovel-skill | MIT | adapted
  - jiaw-Zh/long-novel-writer | 无协议 | idea-only
  - zenstory-ai/oh-story-claudecode | MIT | idea-only
  - chengzhi-c/natural-talk | MIT | adapted
---
# 设定库规则

1. 设定先结构后文字：world / power / faction / character / item / location 六类卡片，每张卡有 name、summary、data。
2. 金手指（power）必须写清三项：怎么用（触发方式）、现阶段能做到哪一步（边界）、怎么升级解锁（成长线）。边界用等级、次数、冷却、触发条件、需要的资源来写，不写自残式代价（永久失去感官、记忆、寿命、亲人，伤害转移到自己身上）。完全没有边界的金手指会让爽点贬值，代价过重的金手指会让读者读不爽。
3. 人物卡入场门禁：写明此刻知道什么、不知道什么、误解什么（data.knows / data.unknown / data.misbelief），以及 known_by（哪些角色知道这张卡上的秘密）。
4. 人物卡说话方式（data 约定键）：voice（说话方式，句长、语气词、称呼习惯）、catchphrases[]（口头禅，1–3 个，克制使用）、habits[]（小动作，具体到身体部位）、demeanor（神态习惯）。不同角色隐去名字后要能分辨谁在说话。
5. 事实分“作者真相”和“读者已知”两条线（visibility = author / reader）。事实只追加，变化时关闭旧事实、写新事实，不改写历史。
6. 主角、主要对手、关键配角至少各一张卡；地点卡写感官锚点（气味、温度、声响、材质），供正文“人动景才出”时取用。
7. 初始事实（facts）的 key 用统一键名，供逐章状态追踪：位置、处境、身体、境界/实力、持有物品、目标、已知信息、关系:对方名字、身份、生死；全书级事实（故事起始时间、局势）entity 写“全书”。
