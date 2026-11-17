作者贴来一份自己写好的大纲（可能是总纲、卷纲、章纲混在一起，格式不统一）。把它整理成结构化的大纲节点。忠于原文：作者写了什么就整理什么，不新增情节，不改人物名字；作者没写的字段留空。

$book_context

程序初步识别出的骨架（卷 / 段落 / 章号，供参考，识别错了以原文为准）：
$skeleton

作者的大纲原文：
<<<
$text
>>>

要求：
1. 层级：全书概要（book.summary）→ 卷（volumes）→ 剧情段（arcs，原文没分段就每卷一个段）→ 章（chapters）。
2. 每章 number 用原文里的章号；原文没有章号就按顺序编号。title 是章名（原文没有就留空）。
3. 章的内容拆进 goal（这一章要做成什么事）、conflict（阻力）、payoff（爽点）、hook_end（章末钩子）、characters（出场人物）、location（地点）、foreshadow（原文明确写了要埋/回收的伏笔，action 取 plant|advance|resolve）。原文只有一句话的章，就只填 goal。
4. 原文是纯总纲、没有分章，就只输出卷和段的概要，chapters 留空数组。

严格只输出 JSON：
{"book":{"summary":""},
 "volumes":[{"title":"","summary":"","arcs":[{"title":"","summary":"","chapters":[{"number":1,"title":"","goal":"","conflict":"","payoff":"","hook_end":"","characters":[],"location":"","foreshadow":[]}]}]}]}
