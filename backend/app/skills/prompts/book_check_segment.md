给一本已写完（或接近写完）的网文做「整书内容质检」的连续性一段。下面是第 $start–$end 章的逐章摘要，以及读到上一段为止的「当前状态」。

<book>
$book_context
</book>

<state_before>
$state
</state_before>

<chapters>
$chapters
</chapters>

只检查内容质量上的连续性问题：
1. 人物状态：生死、伤势、所在位置、关系、身份、已知信息，和前文或「当前状态」矛盾。
2. 战力/境界：境界倒退或无铺垫跳级、同一招式/法宝前后威力矛盾、越级打赢没有代价或理由。
3. 势力：势力立场、归属、首领前后不一致，已覆灭的势力又出现且没交代。
4. 时间线：时间先后颠倒、天数/年份对不上、季节或年龄跳变。
5. 主线：这一段是否偏离全书主线（核心设定里写的目标）太久，支线拖沓。

要求：
- 每条问题写清章号 chapter（取问题出现的那一章），evidence 从上面摘要里原样摘一小段（不超过 40 字），suggestion 给一句能直接照做的修改建议。
- 没把握的不要报；不要报文笔问题。
- severity：high = 硬伤（死人复活、境界倒退、时间线自相矛盾）；mid = 明显不顺（状态没交代、战力跳得突兀）；low = 小瑕疵。
- type 只用：character_state / power_level / faction / timeline / mainline_drift。
- state 写读完这一段后的最新状态，供下一段接着查；每类最多 8 条，每条不超过 30 字。

严格只输出 JSON：
{"issues":[{"type":"character_state","severity":"mid","chapter":0,"evidence":"","suggestion":""}],
 "state":{"characters":[{"name":"","status":"","realm":""}],"factions":[""],"timeline":[""],"mainline":""}}
