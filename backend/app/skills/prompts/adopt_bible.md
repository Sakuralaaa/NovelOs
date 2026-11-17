下面是一本已经写了 $n_chapters 章的网文《$title》的逐章摘要。作者要把这本书接管进写作系统，之后接着往下写。
请从摘要里反推出这本书的底账，只写摘要里能看出来的东西，不要编造摘要里没有的人物和设定。

逐章摘要：
<<<
$summaries
>>>

已有设定卡（不要重复输出同名的卡）：$existing

要求：
1. cards：设定卡。主角必须有一张 character（data.role = "protagonist"），其余重要人物、势力、地点、物品、力量体系、金手指各按需要出卡；
   金手指用 type "cheat"（data 含 input 用法、limit 边界、growth 成长线），力量体系用 type "power"（data.levels 为境界列表）；
   人物 data 尽量带 role、voice（说话方式）；known_by 写知道这条设定的人物名。summary 一两句话。
2. facts：截至最新一章仍然成立的状态事实（谁在哪、什么境界、持有什么、和谁什么关系），entity 写对应卡名，from_chapter 写这条事实开始成立的章号。
3. foreshadows：摘要里埋下但还没回收的伏笔，以及已经回收的伏笔。status 用 planted（已埋未动）/ advancing（推进过）/ resolved（已回收），
   planted_ch 埋下的章号，last_ch 最近一次提到的章号，resolved_ch 回收章号（没回收为 null），tier 用 short / mid / long。

严格只输出 JSON：
{"cards":[{"type":"","name":"","summary":"","data":{},"known_by":[]}],
 "facts":[{"entity":"","key":"","value":"","from_chapter":1}],
 "foreshadows":[{"desc":"","status":"planted","planted_ch":1,"last_ch":1,"resolved_ch":null,"tier":"mid"}]}
