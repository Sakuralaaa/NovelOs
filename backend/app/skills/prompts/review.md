审读第 $number 章。

章细纲：
$chapter_plan

正文：
<<<
$content
>>>

严格只输出 JSON：
{"issues":[{"severity":"high|mid|low","dimension":"hook|pacing|payoff|character|coherence","quote":"从正文原样复制的一句","comment":"问题与改法"}]}
没有问题输出 {"issues":[]}。quote 不在正文里的问题会被丢弃。
