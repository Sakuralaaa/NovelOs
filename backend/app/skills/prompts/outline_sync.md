作者刚改了作品信息，要求把同样的修改同步到大纲。

$book_context

这次的要求：
$instruction

被拿掉或改名的关键概念：$terms
改名对照：$replacements

下面这些大纲节点里出现了这些概念（JSON 行，每行一个）：
$nodes

逐个给出修改后的标题和概要：按要求拿掉、弱化或改名，其余内容原样保留，不新增情节。没必要改的节点不要输出。

严格只输出 JSON：{"nodes":[{"id":0,"title":"","summary":"","reason":"改了什么"}]}
