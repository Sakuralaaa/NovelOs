马上要写第 $number 章。章纲是在动笔前一次排好的，上一章实际写出来的内容可能跑在了章纲前面，或者偏了方向。请对照上一章的真实结尾，校正本章章纲（必要时连下一章一起），让故事从上一章真实停下的地方往前走。

作品：$book

【更早几章摘要】
$recent

【第 $prev_number 章《$prev_title》原定章纲】
$prev_plan

【第 $prev_number 章实际写出的摘要】
$prev_summary

$prev_state

【第 $prev_number 章结尾原文】
$prev_tail

【前文已经结算/提示过的系统面板】
$settled

【第 $number 章现有章纲】
$plan

【第 $number 章的下一章现有章纲】
$next_plan

逐条核对：
1. 本章开头的局面能不能直接接上上一章结尾（人在哪、谁在场、正在发生什么）？
2. 本章要做的事，上一章是不是已经做完了（已经逃出来、已经赢了、已经揭穿、已经到场）？做完了的不许重做，本章往后推一步：处理它的后果、新的麻烦、下一个目标。
3. 本章要结算的奖励、升级、道具，前文是不是已经结算过？同一笔不许再结算；本章换成新的收获，或者写“本章不结算”。
4. 本章 result 和 hook_end 有没有把下一章要写的事提前写完？有就收住，留给下一章。
5. hook_end 只写要发生什么，不写台词原句。

都没问题：{"ok":true,"reason":"一句话"}
有问题：{"ok":false,"reason":"一句话说哪里接不上","chapter":{只给要改的字段},"next":{下一章要跟着改的字段，没有就给 {}}}
可改的字段：title、goal、want、conflict、turn、result、outcome（yes|no|yes-but|no-and）、payoff、payoff_mechanism、cheat_beat、hook_end、opening_hook、expectation、characters、location。
保留原章纲的方向和人物，只改接不上、重复、提前写掉的部分。严格只输出 JSON。
