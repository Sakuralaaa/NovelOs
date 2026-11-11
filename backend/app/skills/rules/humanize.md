---
stage: humanize
title: 去 AI 味与描写增厚规则
version: 0.1
sources:
  - chengzhi-c/natural-talk | MIT | adapted（fiction.md B1–B9、清理边界；SKILL.md 第 7、12、15 条）
  - op7418/Humanizer-zh | MIT | adapted
  - wei125775-lab/deai | MIT | adapted
  - dbhosbu-dotcom/renwei（profiles/fiction）| MIT | adapted
  - KKKKhazix/human-writing | MIT | adapted
  - LAY-lgtm/novel-writing-framework | MIT | adapted
  - evelynyaxueke/anti-ai-writing-kit-zh | MIT | idea-only
---
# 去 AI 味与描写增厚规则

## 原则
1. 一开始写对胜过事后改。事后改写只做定点修补：只改被点名的句子或段落，其余一字不动。
2. 清理以句内优化为主，保留全部有效信息：人名、数字、事件、因果一个都不能丢，不新增事实、不改情节走向。
3. 确定性 lint 放最后一轮复查，因为 LLM 改稿也会带来新口癖。

## 定点清理（patch）
- 翻案腔：无人主张时删掉否定侧，保留肯定侧（“那不是恐惧，是愤怒” → “那是愤怒”）。人物台词不改。
- 叙述破折号：右侧在解释、列举、揭晓的，改成逗号或拆成完整句；台词打断保留。
- 修饰副词：删动作前的微微、轻轻、缓缓、极轻、极慢（微微点头 → 点头）。
- 烂俗比喻与模板表情（嘴角勾起一抹、眼中闪过一丝、心中一凛、倒吸一口凉气）：换成具体动作，或者删掉。
- 翻译腔：当……时、对于……来说、这意味着、段首然而/此外/与此同时，改成顺口的中文语序。
- 情绪直述（一股莫名的情绪涌上心头）：改成看得见的动作、视线停留或身体受力；改不出来就删。

## 描写增厚（thicken）
只处理程序定位出来的段落：
- 裸对白段：给对白配上说话人的动作、神态或身边环境的变化（每段对白至少一半有配）；动作要符合人物卡的 habits / demeanor。
- 概述段：把“经过一番”“很快”“于是”“随后”带过的内容展开成一个小场面：谁、在哪、手上做什么、说了一句什么。
- 短句碎段：把同一主语的连续动作并成一句，长短交替。
- 不得新增人物、物品、设定或情节结果；段落数量与顺序不变；保持原有人称与视点。
