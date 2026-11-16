今天要写的是：$scope_label（快照 $snapshot_label，数据来源：$source_label）。

<boards>
$boards_text
</boards>

<movers>
与上一份快照（$prev_label）相比：
$movers_text
</movers>

每行格式：《书名》｜题材｜标签｜在读｜名次（名次变化）｜简介开头。名次是这本书在它所属题材榜里的名次。

要写的榜（boards 只写这几个，顺序照抄）：$board_names

严格只输出 JSON：
{"hot_words":[{"word":"热词（2–8 字，一个设定、身份、爽点或句式）","why":"一句话：为什么火，落到读者想要的感觉上","examples":["输入里的真实书名"]}],
 "boards":[{"board":"$board_enum","overview":"这个榜今天的样子（2–3 句，点名书）","reader_mood":"读者情绪：他们想要什么感觉","opportunity":"机会判断：现在开坑写什么能起量，为什么（点名新上榜/升幅大的书）","writing_tips":"能直接照做的写作建议","idea_hooks":[{"title":"新书名","pitch":"一句话梗"}]}],
 "open_directions":["今天适合直接开坑的方向，每条一句，具体到设定+身份+爽点"],
 "title_patterns":[{"pattern":"《[可替换位置]……》","examples":["输入里的真实书名"]}],
 "pitfalls":["具体的避坑提醒"]}

数量：hot_words 5–8 个；每个榜 idea_hooks 2–3 个；open_directions 3–5 条；title_patterns 3–6 个；pitfalls 3–6 条。
