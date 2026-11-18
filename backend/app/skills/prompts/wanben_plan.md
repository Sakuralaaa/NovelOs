按字数目标倒推全书卷纲（完本规划）。

$book_context

总纲：
$book_summary

全书目标：约 $target_words 字，每章约 $chapter_words 字，共 $total_chapters 章。
卷的章号区间已经由程序按字数算好，不要改区间：
$volumes

已写到第 $written 章（已写章节的情节不能推翻）。

要求：
1. 每卷写清：卷标题、卷概要（卷目标与主要冲突）、本卷危机（crisis，压在主角身上的最大麻烦）、本卷高潮章（climax_chapter，必须落在本卷区间内，通常在卷末前几章）、本卷收束（closure，卷末解决了什么、留下什么钩子进入下一卷）。
2. 已有标题和概要的卷，只补缺的字段，必要时按新区间微调，不要整卷推翻。
3. 最后一卷必须安排完整结局（finale）：主线终极冲突如何了结（resolution）、哪些长线伏笔在哪几章回收（payoffs）、主要人物的归宿（endings）、最后一章写什么（last_chapter_beat）。结局要落地，不留烂尾，不写“未完待续”。
4. 节奏：卷与卷之间危机逐级升级，每卷都有一次明确的阶段胜利。
5. 卷的篇幅要配得上卷里的事：一卷几十章，就要有几十章的事可写（多个事件、多个对手、多次收获），不能整卷只围着开篇那一场戏打转。开篇的危机和金手指初次收获只占这一卷最前面几章；卷末大爆点是更大的新收获或新地位，不能和开篇已经结算的奖励是同一件。
严格只输出 JSON：
{"volumes":[{"order":1,"title":"","summary":"","crisis":"","climax_chapter":0,"closure":""}],
 "finale":{"resolution":"","payoffs":[""],"endings":[""],"last_chapter_beat":""},
 "ending":"一句话全书结局"}
