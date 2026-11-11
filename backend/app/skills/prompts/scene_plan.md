把下面的章细纲拆成 $min_scenes–$max_scenes 个场景节拍，供逐场景写作。

章细纲：
$chapter_plan

严格只输出 JSON：
{"scenes":[{"goal":"视点人物这场戏想要什么","conflict":"谁或什么在拦","outcome":"yes|no|yes-but|no-and","characters":["在场人物"],"sensory":"一个具体的感官锚点"}]}
连续 3 个 yes 不允许；最后一个场景要承接章末钩子。
