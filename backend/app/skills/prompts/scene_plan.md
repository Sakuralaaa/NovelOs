把下面的章细纲拆成 $min_scenes–$max_scenes 个场景节拍，供逐场景写作。

章细纲：
$chapter_plan

严格只输出 JSON：
{"scenes":[{"goal":"视点人物这场戏想要什么","conflict":"谁或什么在拦","outcome":"yes|no|yes-but|no-and","characters":["在场人物"],"sensory":"一个具体的感官锚点","turn":"这场戏结束时什么变了（信息/关系/计划/风险/权力/情绪之一，写具体）","payoff_phase":"setup|delivery|aftermath","exit_hook":"留给下一场的一个具体悬念"}]}
连续 3 个 yes 不允许；有爽点的章，爽点按“铺垫(setup) → 兑现(delivery) → 余韵(aftermath)”分布在不同场景里，铺垫约占三成；最后一个场景要承接章末钩子。
