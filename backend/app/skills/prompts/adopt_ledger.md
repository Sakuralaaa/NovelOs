接管一本已经写好的小说：读第 $number 章正文，把这一章造成的状态变化记进账本。只记正文里写到的事，不推测后文。

设定库里已登记的名字：
$known

当前仍然有效的状态事实（实体·键=值）：
$facts

还没回收的伏笔：
$open_foreshadows

第 $number 章正文：
<<<
$content
>>>

要求：
1. new_entities：本章第一次出场、之后大概率还会出现的人物/地点/物品/势力（已登记的名字不要重复写）。type 取 character|location|item|faction|world|cheat|power。
2. state_changes：本章结束时发生了变化的状态。entity 写设定库里的名字（或本章新登记的名字），key 用统一键名：位置、处境、身体、境界/实力、持有物品、目标、已知信息、关系:对方名字、身份、生死。value 写变化后的样子，一句话。没有变化的状态不要写。读者已经看到的写 visibility=reader，只有作者知道的写 author。
3. foreshadow：本章新埋下的悬念或线索（action=plant，desc 写清是什么）；推进了上面哪条未回收伏笔（action=advance，id 写编号）；揭晓或了结了哪条（action=resolve，id 写编号）。普通情节不要当伏笔。
4. 宁缺毋滥：不确定就不写。

严格只输出 JSON：
{"new_entities":[{"type":"character","name":"","summary":""}],
 "state_changes":[{"entity":"","key":"","value":"","visibility":"reader"}],
 "foreshadow":[{"action":"plant|advance|resolve","id":null,"desc":""}]}
