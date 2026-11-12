---
stage: chapter_plan
title: 章细纲与场景节拍规则
version: 0.2
sources:
  - xwcai999/opencreator-novel | Apache-2.0 | adapted
  - xiaofeng-928/chinese-longnovel-skill | MIT | adapted
  - LAY-lgtm/novel-writing-framework | MIT | adapted
  - deedeekong07-alt/fiction-humanizer-zh | MIT | adapted
  - danjdewhurst/story-skills | MIT | adapted
  - Tomsawyerhu/Chinese-WebNovel-Skill | 无协议 | idea-only
  - lingfengQAQ/webnovel-writer（爽点三段式铺垫/兑现/微反转）| GPL-3.0 | idea-only
  - socratopia.app 网络小说创作课（期待、压抑、释放三拍）| 文章 | idea-only
---
# 章细纲与场景节拍规则

## 章细纲字段
number、title、goal（本章戏剧问题）、conflict、outcome（yes / no / yes-but / no-and）、payoff（爽点，写成“主语 + 动词 + 宾语 + 对方损失”）、characters[]（必须出场的角色）、location、foreshadow[]（{action: plant/advance/resolve, id, desc}）、hook_end（章末钩子，写到画面）、words。

## 动笔前阻断五问（答不出就改细纲，不许写）
1. 对手这一章造成了什么看得见的伤害或损失？
2. 这一章有没有身体层面的对抗或物理事件（不是纯对话）？
3. 爽点能否写成“主语 + 动词 + 宾语 + 对方损失”？
4. 最后一句会不会让人想立刻翻下一章？
5. 前 300 字有没有发生一件具体的事？

## 章末计划
最后一拍收什么；收在谁的动作、话或决定上；读者下一秒最想知道什么；下一章第一拍怎么接。禁止收在总结句或讲道理上，禁止把悬念解释没。章末钩子优先四种：危机突降、悬念反转、挑衅叫板、倒计时。

## 场景节拍（写正文前先拆）
每章拆成 3–6 个场景节拍，每个节拍写清：
- goal：视点人物在这场戏里想要什么；
- conflict：谁或什么在拦；
- outcome：yes / no / yes-but / no-and 四选一；
- characters：在场人物；
- sensory：一个感官锚点（气味、温度、声响、触感、光线中的一个具体物件）。
每场戏结束时，信息、关系、计划、风险、权力、情绪至少改变一项；每 300–500 字要有一次压力变化。转折必须来自前面的铺垫。

## v0.2 新增可选字段
payoff_type、payoff_level、strand[]、emotion、expectation（本章挂起或兑现的读者期待）、info_gap（信息差）、time（故事内时间）、hook_type、must_avoid[]；foreshadow 的 plant 可带 tier（short / mid / long）。

## 爽点三拍
爽点是读者憋着的那口气吐出来的位置，不是把一段写得更热闹：期待（让读者想看到一件具体的事）→ 压抑（不给，并且“不给”的过程可见、有代价）→ 释放（给，分量配得上压抑的长度）。场景拆分时把三拍落到不同场景：铺垫（setup，约三成篇幅，写清轻视、压迫或信息差）→ 兑现（delivery）→ 余韵（aftermath：围观反应、实际收获、或一个“还有一手”的微反转）。打完必须有收获（资源、认可、资格至少一项）；反派的轻视要基于他已知的信息，不能靠降智。

## 场景节拍新增字段
- turn：这场戏结束时具体改变了什么（信息、关系、计划、风险、权力、情绪之一）；
- payoff_phase：setup / delivery / aftermath；
- exit_hook：留给下一场的一个具体悬念。

## 写前核对（程序执行）
动笔前程序会核对：细纲人物是否在设定库、是否已登记死亡；地点是否登记；要推进/回收的伏笔是否还在伏笔池；有没有超过 40 章没动的伏笔。核对结果放进“写前核对”，写作时必须照做。
