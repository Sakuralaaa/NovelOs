接管一本已经写了一部分的小说：从第 $start–$end 章的内容里反推设定卡。只写正文里真的出现或能明确推出的东西，不要替作者发明新设定。

$book_context

设定库里已有的卡（类型、名字、一句话）：
$existing

第 $start–$end 章的章节摘要（没有摘要的章给的是正文开头）：
$digest

要求：
1. 重点找这几类：主角与反复出场的人物（character）、世界观与时代背景（world）、主角的特殊能力或外挂（cheat）、等级或实力体系（power）、组织与势力（faction）、关键物品（item）、反复出现的地点（location）。只出场一次的路人不要建卡。
2. 已有卡里出现过的东西，用 action=update、target 写旧卡名，只写这几章带来的新信息（身份揭晓、实力变化、关系变化等）；没有新信息就不要输出这张卡。新东西用 action=add。
3. 人物卡 data 里尽量写：role（protagonist / antagonist / ally / other）、identity（身份）、voice（说话方式，从对白里总结）、relations（和谁是什么关系）、first_chapter（第一次出现的章号）。能力外挂卡 data 写 input（怎么触发）、limit（限制）、growth（怎么变强）。地点卡 data 写 sensory（正文里写过的样子、声音、气味）。
4. known_by 写这条信息在正文里有哪些角色知道（秘密才需要写）。
5. 不确定的信息不要写成定论，可以在 summary 里写「（正文暗示）」。

严格只输出 JSON：
{"cards":[{"action":"add|update","target":"","type":"world|cheat|power|faction|character|item|location","name":"","summary":"","data":{},"known_by":[]}]}
