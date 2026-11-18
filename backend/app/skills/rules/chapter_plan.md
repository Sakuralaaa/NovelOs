---
stage: chapter_plan
title: 章细纲（读者账本）与段落安排规则
version: 0.17.1
sources:
  - xwcai999/opencreator-novel | Apache-2.0 | adapted
  - xiaofeng-928/chinese-longnovel-skill | MIT | adapted
  - LAY-lgtm/novel-writing-framework | MIT | adapted
  - deedeekong07-alt/fiction-humanizer-zh | MIT | adapted
  - danjdewhurst/story-skills | MIT | adapted
  - Tomsawyerhu/Chinese-WebNovel-Skill | 无协议 | idea-only
  - lingfengQAQ/webnovel-writer（爽点三段式铺垫/兑现/微反转）| GPL-3.0 | idea-only
  - socratopia.app 网络小说创作课（期待、压抑、释放三拍）| 文章 | idea-only
  - wangwen666.com/post/204 2026-06-04（番茄冲突 ≤500 字、金手指 ≤1000 字；主角不能一直窝囊，要有反击苗头）| 文章 | idea-only
  - maliangwriter.com 黄金三章检查 2026-08-01（入局/加压/承诺）| 文章 | idea-only
  - Narcooo/inkos（reader-contract-and-progression：金手指可见使用、每章改变主轴）| AGPL-3.0 | idea-only
  - 猫腻访谈（看对方怎么输；安全感上叠一层可控的不安全感）| 访谈 | idea-only
---
# 章细纲规则：读者账本

## 每章必填（读者账本）
- want：主角本章主动想要什么。写成他要去争、去拿、去查、去赢的东西；连续两章以上只写躲、逃、撑过、保住，读者会憋屈。
- conflict：阻力，谁或什么在拦，拦得多狠。
- turn：转折，局面在哪一刻掉头（新信息、对手失算、金手指出手、有人反水）。
- result：结果，本章结束时主角得到了什么、失去了什么、局面变成什么样；outcome 用 yes / no / yes-but / no-and 标一下。
- cheat_beat：金手指本章怎么用、怎么兑现。每章都写；可以写“本章不用”，但每 3 章至少一次可见的兑现，并且带来具体收获（数字、能力、物品、名次、对手的反应）。金手指只给好处，紧迫感来自对手和困境。
- payoff_mechanism：爽点机制一句话：谁输、怎么输、谁看见、主角得到什么。和最近 5 章不能是同一种机制（同样是“当众说出对方秘密”就算重复）。
- hook_end：章末最后一拍：停在哪个事件进行中，或停在谁的哪一句话上（写要发生什么，台词原句留给写手）。
- 其它：title、payoff（爽点一句话）、payoff_type、payoff_level（small / combo / milestone；milestone = 改变主角地位的大爽点）、characters[]、location、foreshadow[]（{action: plant/advance/resolve, id, desc}）、expectation（本章挂起或兑现的读者期待）。

## 开篇（程序兜底补齐）
- opening_hook（第 1–3 章必填）：正文前三行就发生的冲突或异常，写成画面。
- 第 1 章：主角出场就在做事并撞上麻烦；金手指露一次读者能感知的苗头。第 2 章金手指第一次真正用出来并有收获。第 3 章给第一次小胜，把短期冲突接到长线目标上。
- 第 1–3 章每章主角都要亲自压对手一次，并拿到一个读者看得见的收获（实力、名额、钱、打脸、关系之一）。

## 节奏
- 相邻两章的 hook_type 和章末画面换着来；爽点模式不连续三章相同。
- 同一个信息只在一章里交代一次。
- 本章开头接上一章 result；上一章已经完成的事不重做，已经结算的奖励不再结算（v0.17.1）。
- result 写清本章停在哪个节点；后面章节的事件不提前写进本章的 result、hook_end。
- 动笔前五问（答不出就改细纲）：主角这章要什么？谁在拦？哪一刻掉头？谁输了、谁看见？最后一拍停在哪？

## 段落安排（写正文前排）
每章排成 3–6 段，每段写清 goal（主角这段想要什么）、conflict（谁在拦）、turn（这段结束时什么变了）、outcome、characters、payoff_phase（setup / delivery / aftermath）、cheat（本段金手指怎么用，可省略）。
只写事件和局面的变化，台词原句、钩子原句、感官细节和比喻都留给写手。
爽点三拍：期待（让读者想看到一件具体的事）→ 压抑（不给，过程看得见）→ 释放（给，分量配得上压抑）。期待和压抑约占三成，释放后给围观反应或实际收获。反派的轻视要基于他已知的信息，不靠降智。

## 写前核对（程序执行）
动笔前程序会核对：细纲人物是否在设定库、是否已登记死亡；地点是否登记；要推进/回收的伏笔是否还在伏笔池；有没有超过 40 章没动的伏笔。
