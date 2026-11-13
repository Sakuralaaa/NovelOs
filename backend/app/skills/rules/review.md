---
stage: review
title: 证据式审稿规则
version: 0.6
sources:
  - wfcz10086（evidence-based review）| Apache-2.0 | idea-only
  - lingfengQAQ/webnovel-writer | GPL-3.0 | idea-only
  - MintoTsukino/claude-novel-workflow | CC BY 4.0（文档） | adapted
  - xwcai999/opencreator-novel | Apache-2.0 | adapted
  - 304769384-png/fanqie-novel-skill | 无协议 | idea-only
  - Tomsawyerhu/Chinese-WebNovel-Skill | 无协议 | idea-only
  - XuanRanL/webnovelwriter（六维审查：爽点/一致性/节奏/OOC/连贯/追读力）| GPL-3.0 | idea-only
  - maliangwriter.com 黄金三章检查（章尾四种断法：决定/发现/误判/代价）| 文章 | idea-only
---
# 证据式审稿规则

1. 只报问题，不打分。分数由程序按问题数量和严重度计算。
2. 每条问题必须带 quote：从正文里原样复制的一句话（不改一个字、不加省略号）。程序会校验 quote 是否真在正文里，找不到的问题直接丢弃。
3. 维度（dimension）只用七个：hook（开头与章末钩子）、pacing（节奏与概述化）、payoff（爽点兑现）、character（人物言行一致、声口区分、OOC）、coherence（设定与底账、上一章一致）、continuity（本章内部的连续性与物理逻辑：道具、服装装备、站位朝向、角度数字、身体）、semantics（语义写反、搭配与量词错误、指代不清）。
4. 严重度：high = 设定冲突、人物 OOC、细纲要求的关键事件没写、章末无钩子；mid = 爽点虚、节奏拖、对白呆板（裸对白、短句乒乓）、概述代替场面；low = 措辞、AI 腔。
5. 章末四层诊断：没有落点 / 有落点没后劲 / 硬钩感太重 / 与下一章接不上。
6. “话疗”检查：大反派不能被几句话说服。
7. 审稿时不看大纲以外的猜测，不编造正文中没有的内容。

## v0.2 审稿核对清单
8. 审稿会拿到“人物与世界当前状态 + 上一章结尾”。位置、伤势、持有物品、时间、生死与之矛盾 → coherence/high；角色说出或利用了他“已知信息”之外的秘密 → character/high（认知越界）。
9. 爽点（payoff）按三段看：有没有铺垫（轻视、压迫、信息差）、兑现是否写成场面、之后有没有反应或实际收获。降智反派、一招秒杀无势能、打完无收获 → payoff/mid。
10. 追读力并入 hook：前 300 字有没有具体事件；章末是否断在决定/发现/误判/代价上；章末若是总结、升华、空泛预告 → hook/mid（程序也会自动检查最后一句）。黄金三章额外看钩子是否一章比一章更贴近主角。
11. 细纲要求的伏笔动作没写到 → coherence/mid；细纲 must_avoid 里的内容被写出来 → coherence/high。

## v0.6 连续性与语义（逐条引用原句）
12. continuity：先在心里按出场顺序给每个道具、衣着装备、站位朝向、身体状态记流水账，再找前后矛盾。每条 quote 放后出现的那句，comment 写“前文「…」，此处「…」，矛盾在于…，改成…”。道具凭空换位置/换手、同一物件描述不一、离场的人或车还在影响现场 → mid；主角/对手的服装装备或身体部位前后矛盾 → mid；影响爽点成立的物理错误（打脸动作前后对不上）→ high。
    - 例：前文「他手里夹着一份硬壳烫金合同」，此处「一把抓起那叠厚纸」：合同从没离开韩铎的手，也从硬壳变成了厚纸。
13. semantics：意思写反（贬低却写“没有上限”）、称呼与关系不符（自称补录的人张口叫“师父”）、量词搭配错误（一柄铁砣）→ mid/low。
14. 节奏补充：前三段只有氛围没有冲突 → hook/mid（第 1–3 章 high）；第 1 章金手指/卖点没有露面 → payoff/mid；群众反应镜头超过 3 个、章末连抛三个钩子 → pacing/mid；主角全程没有内心 → character/low。

