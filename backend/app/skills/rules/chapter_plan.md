---
stage: chapter_plan
title: 章细纲与场景节拍规则
version: 0.6
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
---
# 章细纲与场景节拍规则

## 章细纲字段
number、title、goal（本章戏剧问题）、conflict、outcome（yes / no / yes-but / no-and）、payoff（爽点，写成“主语 + 动词 + 宾语 + 对方损失”）、characters[]（必须出场的角色）、location、foreshadow[]（{action: plant/advance/resolve, id, desc}）、hook_end（章末钩子，写到画面）、words。

## v0.6 开篇硬字段（程序兜底补齐）
- opening_hook（第 1–3 章必填）：正文前三行就发生的冲突或异常，写成画面，不写“气氛压抑”。
- cheat_beat（第 1 章必填）：金手指/核心卖点在本章露出的具体苗头：谁做了什么，主角感到什么可感知的反馈。卖点是“收徒涨修为”，第 1 章就要有人递上拜师/补录表并让主角感到一次“涨”的苗头，不能整章只打脸不露卖点。
- 场景拆分时：第一个场景从 opening_hook 起；cheat_beat 落到兑现场景；群众反应镜头全章 ≤3；只有最后一个场景承接 hook_end，章末只留一个主钩。
- 新人物或容易误读的关系，在场景 relations 里写清关系和称呼依据。

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

## 开篇节奏（番茄向，2026-11 实测补充）
- 第 1–3 章每章都要有一个读者看得见的收获（实力、名额、钱、打脸、关系之一），outcome 不用 no-and，emotion 不连续两章 down。
- 第 1–3 章每章主角都要亲自压对手一次：当面回击、让对手失算或吃亏，payoff 写清“谁当场丢了什么”。主角不能整章只在旁边看徒弟受苦。
- 相邻两章的 hook_type 和章末画面不能相同（上一章结尾受伤，下一章结尾就换成发现、反转或更大的对手）。
- 第 2 章要完成「被压 → 反击」：金手指第二次使用就要比第一次更具体（能说清涨了多少、补上了哪一处），不要只写“暖流”“往上蹿了一截”。
- 同一个信息只在一章里交代一次：上一个场景已经办完的手续、已经亮过的底牌，下一个场景不再走一遍。

## 场景节拍新增字段
- turn：这场戏结束时具体改变了什么（信息、关系、计划、风险、权力、情绪之一）；
- payoff_phase：setup / delivery / aftermath；
- exit_hook：留给下一场的一个具体悬念。

## 写前核对（程序执行）
动笔前程序会核对：细纲人物是否在设定库、是否已登记死亡；地点是否登记；要推进/回收的伏笔是否还在伏笔池；有没有超过 40 章没动的伏笔。核对结果放进“写前核对”，写作时必须照做。
