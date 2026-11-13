审读第 $number 章。

<chapter_plan>
$chapter_plan
</chapter_plan>

<ledger>
写这一章前的底账（人物与世界当前状态、上一章结尾；正文与之矛盾就是 coherence 问题）：
$context
</ledger>

<chapter>
$content
</chapter>

先通读全文，按出场顺序给每个道具、每个人的衣着装备、站位朝向、身体状态记一笔流水账（只在心里记，不输出），再逐项核对：
1. hook：前三行有没有冲突或异常；前 300 字有没有具体事件；章末是否只有一个主钩（至多一个副钩），断在决定/发现/误判/代价上。
2. payoff：细纲的爽点与 cheat_beat（金手指苗头）有没有写成读者能感知的场面；铺垫 → 兑现 → 反应或收获是否完整。
3. pacing：概述代替场面、前几段纯氛围、群众反应镜头超过 3 个、章末钩子堆叠。
4. character：言行与人物卡、已知/未知边界是否一致；称呼与关系是否自洽（叫“师父”就得已入门）；主角是否全程没有内心。
5. coherence：与底账、上一章结尾、细纲事件和伏笔动作是否一致。
6. continuity（连续性与物理逻辑）：道具凭空换位置或换手、同一物件前后描述不一（硬壳 ↔ 一叠厚纸）、服装鞋子装备前后不一（皮鞋 ↔ 金属脚掌）、角度数字前后不一（钝角 ↔ 九十度）、身体部位写错（金属臂不会“胀得发紫”）、朝向矛盾（本就面朝门外又“转过身来迎着门外”）、离场的人或车还在影响现场（车开走了灯还照进屋）。
7. semantics（语义正确）：贬褒写反、否定写反、因果写反、量词或搭配错误、指代不清。

continuity 与 semantics 的每一条：quote 放后出现的那句矛盾原句，comment 写成“前文「……」，此处「……」，矛盾在于……，改成……”。

严格只输出 JSON：
{"issues":[{"severity":"high|mid|low","dimension":"hook|pacing|payoff|character|coherence|continuity|semantics","quote":"从正文原样复制的一句","comment":"问题与改法"}]}
没有问题输出 {"issues":[]}。quote 不在正文里的问题会被丢弃。
