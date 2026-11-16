给这本网文的第 $start–$end 章做「短剧可改编度」审读：判断改编成竖屏短剧（每集 1–2 分钟）的潜力。

<book>
$book_context
</book>

<characters>
$characters
</characters>

<metrics>
程序统计（仅供参考）：
$metrics
</metrics>

<excerpts>
$excerpts
</excerpts>

按下面六项各打 0–10 分，并给一句理由：
- persona：人设极致度——主角/反派/关键配角有没有一眼记住的极端标签，行为是否持续强化它。
- conflict：冲突密度——每章冲突是否密集、有没有拖沓过场。
- reversal：反转速度——身份揭露、立场翻转、局势逆转来得够不够快。
- shootability：场景数与可拍性——场景是否集中、可拍（少大场面特效、少纯心理）。
- dialogue：对白占比——台词能不能直接当剧本念。
- episodes：每章可切成几集——给出整体估计 per_chapter（数字，可带一位小数）。

再给 3–6 条改进建议 suggestions（每条一句，能直接照做），以及最多 10 条逐章备注 chapter_notes（chapter、episodes 估计集数、note 一句话）。

严格只输出 JSON：
{"scores":{"persona":{"score":0,"comment":""},"conflict":{"score":0,"comment":""},"reversal":{"score":0,"comment":""},
 "shootability":{"score":0,"comment":""},"dialogue":{"score":0,"comment":""},"episodes":{"score":0,"comment":"","per_chapter":0}},
 "suggestions":[""],"chapter_notes":[{"chapter":0,"episodes":1,"note":""}]}
