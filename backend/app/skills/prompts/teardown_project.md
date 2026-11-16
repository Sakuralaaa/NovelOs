你是一位只研究写法、不搬运内容的网文拆书编辑。下面是作者给的参考材料$source_label。请把它拆成能迁移到新书的结构知识。

$meta

<material>
$text
</material>

$notes

拆书要求：
- 只提炼结构、节奏、人设功能和机制设计；不要复述原文句子，任何一句都不要连续照抄 8 个字以上。
- 产物里一律不要出现原书的书名、作者、人名、地名、组织名、招式名等专有名词：人物用「主角」「师姐型配角」「前期反派」这类功能称呼，地点用「主城」「宗门」这类泛称，机制用通用描述。
- structure：opening 写开篇怎么入局（第几段出冲突、主角在做什么）；rhythm 写整体节奏打法；chapter_hooks 列 3–6 种章末钩子手法（各 30 字内）。
- characters：3–6 个人设模板，role 是功能称呼，template 写这个模板的通用描述（60 字内），traits 3 个标签，function 写他在情节里干什么。
- golden_finger：mechanism 机制原理、limits 限制与代价、growth 成长路线、payoff 它怎么给读者爽感；材料里没有金手指就写清「无明显金手指」并说明替代爽点来源。
- selling_points：3–6 条卖点（每条 30 字内）。
- pacing_chart：按材料里能分辨的章节逐章打分（没有分章就按情节段落），conflict 冲突强度、payoff 爽点强度、hook 章末钩子强度，都是 1–5 的整数，note 一句话（20 字内）；最多 30 章。
- reusable：3–8 条可复用套路，name 套路名、pattern 去专名后的结构描述、how_to_use 怎么用到新书（各 60 字内）。
- names：把材料里出现的原书专有名词（人名、地名、组织、功法、书名）列出来，最多 30 个——这一项只用于程序过滤，不会展示。

严格只输出 JSON：
{"structure":{"opening":"","rhythm":"","chapter_hooks":[""]},
 "characters":[{"role":"","template":"","traits":["",""],"function":""}],
 "golden_finger":{"mechanism":"","limits":"","growth":"","payoff":""},
 "selling_points":[""],
 "pacing_chart":[{"chapter":1,"title":"","conflict":3,"payoff":2,"hook":4,"note":""}],
 "reusable":[{"name":"","pattern":"","how_to_use":""}],
 "names":[""]}
