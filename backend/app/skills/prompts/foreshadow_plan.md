为这本书规划伏笔。

$book_context

大纲（总纲 / 卷 / 弧 / 已规划的章细纲）：
$outline

已有的伏笔（不要重复）：
$existing

已写到第 $current 章（伏笔要埋在还没写的章里，即第 $next 章以后）。

作者的要求：
$instruction

要求：给出 $count 条伏笔，长短线搭配（short 10 章内回收、mid 30 章内、long 50 章以上）；每条写清埋在哪一章（plant_ch）、预计哪一章回收（resolve_ch，长线可以超出当前大纲）、怎么埋怎么收（note）。伏笔要和设定库、大纲咬合，不要凭空引入大设定。

严格只输出 JSON：{"foreshadows":[{"desc":"伏笔内容，一句话","tier":"short|mid|long","plant_ch":0,"resolve_ch":0,"note":"怎么埋、怎么收","related":["相关人物或设定名"]}]}
