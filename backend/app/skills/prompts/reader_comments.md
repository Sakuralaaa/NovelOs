你要模拟番茄小说读者给第 $number 章写「段评」。下面是几位读者的画像，每人都按自己的口味读：
$personas

<chapter>
$content
</chapter>

要求：
- 每位读者写 2–3 条段评，每条必须挂在正文里原样存在的一句话上（quote 原样复制，不在正文里的会被丢掉）。
- 段评要像真读者：短、口语、有情绪，可以夸、可以吐槽、可以催更、可以猜后续；不要写成编辑点评。
- 每位读者最后说一句会不会追下一章（will_continue: true/false），以及想划走的地方（drop：原样引一句，没有就空字符串）。

严格只输出 JSON：
{"comments":[{"persona":"读者名","quote":"","text":"","mood":"爽|笑|急|烦|猜"}],
 "verdicts":[{"persona":"读者名","will_continue":true,"drop":"","why":""}]}
