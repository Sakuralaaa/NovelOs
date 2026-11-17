接管一本已经写好的小说：根据第 $start–$end 章的摘要和章末原文，反推每章的结构化细纲，并标出节奏。细纲描述的是已经写出来的内容，不要改情节。

$book_context

已登记的人物：$names

各章内容：
$chapters

每章要写：
- goal：这一章的戏剧问题（主角想做成什么）；conflict：挡在面前的阻力；outcome：结果（yes 得手 / no 失手 / yes-but 得手但有代价 / no-and 失手且更糟）。
- payoff：这一章给读者的爽点或满足感是什么；payoff_type 从 打脸 / 扮猪吃虎 / 越级反杀 / 打脸权威 / 反派翻车 / 甜蜜超预期 / 真相揭示 / 收获升级 / 危机化解 / 关系突破 里选最接近的一个（都不像就留空）；payoff_level：small / combo / milestone。
- strand：这一章主要推进哪条线（quest 主线 / fire 感情与人物关系 / constellation 世界观与势力），可多选；emotion：读者情绪走向 up / down / flat。
- hook_end：章末停在什么画面或悬念；hook_type 从 危机突降 / 悬念反转 / 挑衅叫板 / 倒计时 / 信息缺口 / 选择悬置 / 后果预示 / 决定 / 发现 / 误判 / 代价 里选。
- characters：出场的主要人物（用已登记的名字）；location：主要地点；expectation：这一章挂起或兑现了读者的什么期待。
另外用一两句话概括这几章合起来是一段什么剧情（arc）。

严格只输出 JSON：
{"arc":{"title":"不超过 10 个字","summary":""},
 "chapters":[{"number":0,"goal":"","conflict":"","outcome":"yes|no|yes-but|no-and","payoff":"","payoff_type":"","payoff_level":"small",
   "strand":["quest"],"emotion":"up","characters":[],"location":"","expectation":"","hook_end":"","hook_type":""}]}
