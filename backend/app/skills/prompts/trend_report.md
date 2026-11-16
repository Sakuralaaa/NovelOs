今天要写的是：$scope_label（快照 $snapshot_label，数据来源：$source_label）。每个榜读前 $top_n 本。

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
{"headline":"一句话定调，40 字内，点出今天最强的两股风和最吃香的写法，例如「灵异职业化与系统返还双主线，弱起点强结算最吃香」",
 "summary":"2–3 句总述：今天榜上发生了什么、对开新书意味着什么（点名书）",
 "hot_words":[{"word":"热词（2–8 字，一个设定、身份、爽点或句式）","why":"一句话：为什么火，落到读者想要的感觉上","examples":["输入里的真实书名"]}],
 "boards":[{"board":"$board_enum","overview":"这个榜今天的样子（2–3 句，点名书）","reader_mood":"读者情绪：他们想要什么感觉","opportunity":"机会判断：现在开坑写什么能起量，为什么（点名新上榜/升幅大的书）","writing_tips":"能直接照做的写作建议","risks":"这个榜上跟风最容易翻车的地方","idea_hooks":[{"title":"新书名","pitch":"一句话梗"}]}],
 "inspirations":[{"title":"新书名（原创，不和榜上书重名）","logline":"一句话钩子","protagonist":"主角：身份 + 处境 + 性格底色","mechanism":"核心机制 / 金手指：怎么触发、怎么越用越强","opening":"第一章开局：第一个场面和第一次兑现","selling_points":["短卖点1","短卖点2","短卖点3"],"board":"$board_enum（借的是哪个榜的风）"}],
 "opening_hooks":["开篇钩子写法：一句说清第一章前三百字怎么抓人"],
 "plot_devices":[{"name":"剧情装置名（如：倒计时结算、规则反噬）","desc":"怎么用、为什么现在读者吃这一套"}],
 "writing_advice":"给今天开新书的作者的整体写作建议（3–5 句，能直接照做）",
 "risk_alerts":["整体风险提醒：跟风翻车点、平台审核红线、读者已经腻了的写法"],
 "open_directions":["今天适合直接开坑的方向，每条一句，具体到设定+身份+爽点"],
 "title_patterns":[{"pattern":"《[可替换位置]……》","examples":["输入里的真实书名"]}],
 "pitfalls":["具体的避坑提醒"]}

数量：hot_words 5–8 个；每个榜 idea_hooks 2–3 个；inspirations 4–6 条（每条 selling_points 正好 3 条，每条 15 字内）；opening_hooks 3–5 条；plot_devices 3–5 个；risk_alerts 3–5 条；open_directions 3–5 条；title_patterns 3–6 个；pitfalls 3–6 条。
