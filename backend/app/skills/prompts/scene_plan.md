把下面的章细纲拆成 $min_scenes–$max_scenes 个场景节拍，供逐场景写作。

$book_context

<chapter_plan>
$chapter_plan
</chapter_plan>

程序附加要求（必须照做）：
$opening_rules

严格只输出 JSON：
{"scenes":[{"goal":"视点人物这场戏想要什么","conflict":"谁或什么在拦","outcome":"yes|no|yes-but|no-and","characters":["在场人物"],"relations":"在场人物与视点人物的关系和称呼依据（可空）","sensory":"一个具体的感官锚点","turn":"这场戏结束时什么变了（信息/关系/计划/风险/权力/情绪之一，写具体）","payoff_phase":"setup|delivery|aftermath","cheat":"本场金手指露出的具体画面（没有就省略）","exit_hook":"留给下一场的一个具体小悬念（最后一场省略）"}]}
连续 3 个 yes 不允许；有爽点的章，爽点按“铺垫(setup) → 兑现(delivery) → 余韵(aftermath)”分布在不同场景里，铺垫约占三成；最后一个场景承接章末钩子，只留一个主钩。
