你是一位熟悉同人创作的资料编辑。作者想写《$work》的同人，下面是联网检索得到的原著资料（第 $part / $parts 段），请把它整理成「原著设定卡」，供作者写同人时对照人设。

注意：这些资料来自联网检索，可能有误、可能混入同人二设或不同版本（小说/动画/游戏/电影）的差异。只写多条资料一致、或明确标注为原著设定的内容；不确定、有争议、只出现在同人圈的说法一律不写。

$meta

<material>
$text
</material>

$notes

整理要求：
- 一律用你自己的话概括，不要复述资料里的长句；口头禅只写短句。
- 名字保留原著写法（同人需要原名）；同一人物的别称、外号写进 aliases。
- characters：重要人物，主角在前。personality 性格（60 字内）；speech_style 说话方式（40 字内）；catchphrases 口头禅（每条 20 字内，最多 4 条，没有或不确定就留空数组）；relations 和其他人物的关系（target 对方名字、relation 关系，20 字内）；abilities 能力/身份带来的本事（各 20 字内）；limits 能力上限与做不到的事（各 30 字内）；role 在故事中的位置（主角/主要配角/反派/…）。
- world：summary 世界观概述（120 字内）；rules 世界规则、力量体系等级与关键约束（各 40 字内，最多 8 条）；locations 重要地点（名字 + 一句话）。
- factions：势力或组织，stance 立场、members 成员名、notes 一句话。
- timeline：关键事件，按原著先后顺序，event 用自己的话写（40 字内），characters 涉及人物，impact 对后续的影响（30 字内）。
- scenes：名场面，title 短名，summary 用自己的话概括发生了什么、为什么动人（80 字内），characters 涉及人物。
- 资料里没有的内容就给空数组，不要凭印象补写。

严格只输出 JSON：
{"characters":[{"name":"","aliases":[""],"role":"","personality":"","speech_style":"","catchphrases":[""],"relations":[{"target":"","relation":""}],"abilities":[""],"limits":[""]}],
 "world":{"summary":"","rules":[""],"locations":[{"name":"","desc":""}]},
 "factions":[{"name":"","stance":"","members":[""],"notes":""}],
 "timeline":[{"event":"","characters":[""],"impact":""}],
 "scenes":[{"title":"","summary":"","characters":[""]}]}
