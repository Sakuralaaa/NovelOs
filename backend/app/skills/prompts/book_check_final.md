给一本网文做「整书内容质检」的收尾判断：结局是否仓促/烂尾、主线是否跑偏。

<book>
$book_context
</book>

<outline>
$outline
</outline>

<state_at_end>
$state
</state_at_end>

<volume_digest>
$digest
</volume_digest>

<last_chapters>
$last_chapters
</last_chapters>

<last_chapter_tail>
$tail
</last_chapter_tail>

本书共 $chapter_count 章，约 $total_words 字；还没回收的伏笔：$open_foreshadows

请判断：
1. 结局 ending：主要矛盾有没有在最后几章正面解决；关键人物有没有交代；高潮到收尾的篇幅是否过短（仓促）；有没有停在悬念上没收（烂尾）。rushed=true 表示仓促或烂尾。
2. 主线 mainline：对照核心设定与大纲，全书有没有长时间偏离主线、主线目标是否兑现。drift=true 表示明显跑偏。
3. 其他整书级问题 issues（最多 6 条），type 只用：ending_rushed / ending_open / mainline_drift / character_state / power_level / faction / timeline。
每条带 chapter（没有具体章写 0）、evidence（原样摘一小段，不超过 40 字）、suggestion（能直接照做）、severity（high/mid/low）。只评内容质量。

严格只输出 JSON：
{"ending":{"rushed":false,"score":0,"comment":"","evidence":""},
 "mainline":{"drift":false,"score":0,"comment":"","evidence":""},
 "issues":[{"type":"ending_rushed","severity":"mid","chapter":0,"evidence":"","suggestion":""}],
 "summary":""}
其中 score 为 0–10 分。
