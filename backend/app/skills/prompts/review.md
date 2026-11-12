审读第 $number 章。

章细纲：
$chapter_plan

写这一章前的底账（人物与世界当前状态、上一章结尾；正文与之矛盾就是 coherence 问题）：
$context

正文：
<<<
$content
>>>

逐项核对后再报问题：
1. hook：前 300 字有没有具体事件；章末是否断在决定/发现/误判/代价上；钩子类型是否与细纲一致。
2. payoff：细纲的爽点有没有兑现；是否有铺垫（轻视/压迫/信息差）→ 兑现 → 反应或收获；有没有降智反派、打完无收获。
3. pacing：有没有概述代替场面、连续说明、拖沓；每场戏是否有变化。
4. character：言行是否符合人物卡与已知/未知边界（角色不能知道没亲眼见过、也没人告诉过的事）。
5. coherence：位置、伤势、持有物品、时间、生死是否与底账和上一章结尾一致；细纲要求的事件与伏笔动作是否写到。

严格只输出 JSON：
{"issues":[{"severity":"high|mid|low","dimension":"hook|pacing|payoff|character|coherence","quote":"从正文原样复制的一句","comment":"问题与改法"}]}
没有问题输出 {"issues":[]}。quote 不在正文里的问题会被丢弃。
