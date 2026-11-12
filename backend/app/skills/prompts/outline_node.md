按作者的要求重写大纲里的一个节点（$node_level）的标题和内容概要。

$book_context

上一层：$parent
同级节点：$siblings
下一层已有：$children

当前节点：
标题：$node_title
概要：$node_summary

作者的要求：
$instruction

要求：只改这一个节点；和上一层、同级节点保持衔接，不要和下一层已经写好的内容矛盾（除非作者要求改）。$level_rule

严格只输出 JSON：{"title":"","summary":"","change":"这次改了什么，一句话"}
