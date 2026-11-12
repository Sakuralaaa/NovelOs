$mode_task

$book_context

现有设定卡（JSON 行，每行一张）：
$existing

作者的要求：
$instruction

$scope

严格只输出 JSON：
{"cards":[{"action":"add|update","target":"update 时写要改的旧卡名，add 时留空","type":"world|cheat|power|faction|character|item|location",
  "name":"","summary":"","data":{},"known_by":[],
  "conflicts":[{"name":"与之冲突的已有卡名","reason":"哪里矛盾（同名、事实矛盾、金手指重复等）"}]}],
 "facts":[{"entity":"卡片名","key":"","value":"","visibility":"author|reader"}],
 "change":"这次做了什么，一句话"}
如果新卡和已有卡有冲突，照实写进 conflicts，不要为了避免冲突而不写；程序会让作者逐条决定。
