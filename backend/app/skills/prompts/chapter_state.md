下面是第 $number 章《$chapter_title》的正文。只根据正文里真写到的内容，抽取两样东西。

一、本章结束那一刻的场面状态 state（只写结尾时在场或刚离场的人物、出现过的道具）：
$schema_hint

二、变更声明 changes：
- new_entities：正文里第一次出现、后面还会用到的人物、物品、地点、势力、能力（设定库已有的名字不要写）。
- state_changes：人物和世界在本章发生的变化，key 尽量用：位置、处境、身体/伤势、境界/实力、持有物品、情绪、目标、已知信息、关系:对方名字、身份、生死；全书级变化（时间、局势）entity 写“全书”。角色得知秘密时登记“已知信息”。
- foreshadow：本章埋下（plant）、推进（advance）、回收（resolve）的伏笔；推进和回收要带下面列出的伏笔编号 id。

设定库里已有的名字：$known
未回收的伏笔：
$opens
细纲安排的伏笔动作：$planned

上一章结束时的状态（对照用）：
$prev_state

<chapter>
$content
</chapter>

严格只输出 JSON：
{"state":{"cast":[],"props":[],"env":""},
 "changes":{"new_entities":[{"type":"character|item|location|faction|cheat|power|world","name":"","summary":""}],
            "state_changes":[{"entity":"","key":"","value":"","visibility":"reader|author"}],
            "foreshadow":[{"action":"plant|advance|resolve","id":null,"desc":""}]}}
没有的写空数组。
