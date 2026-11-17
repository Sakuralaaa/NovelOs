把下面的章细纲排成 $min_scenes–$max_scenes 段，供写手整章一次写完。每段只写要发生什么、局面怎么变。

$book_context

<chapter_plan>
$chapter_plan
</chapter_plan>

程序附加要求（必须照做）：
$opening_rules

每段写清：主角这段想要什么（goal）、谁或什么在拦（conflict）、转折是什么（turn）、结果（outcome）、在场人物、在爽点里的位置。
只写事件和局面的变化：不写台词原句、不写钩子原句、不写感官细节和比喻，这些留给写手。

严格只输出 JSON：
{"scenes":[{"goal":"","conflict":"","turn":"这段结束时什么变了（信息/关系/计划/风险/实力/情绪之一）","outcome":"yes|no|yes-but|no-and","characters":["在场人物"],"relations":"新人物和主角的关系与称呼依据（可空）","payoff_phase":"setup|delivery|aftermath","cheat":"本段金手指怎么用、给了什么（没有就省略）"}]}
连续 3 个 yes 不允许；有爽点的章，期待和压抑约占三成，释放写在后半段；最后一段落到章末最后一拍。
