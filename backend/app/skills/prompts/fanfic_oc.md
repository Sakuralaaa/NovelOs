为同人书《$title》设计原创主角。原著：$source_title；遵循度：$fidelity_label；创作方向：$direction。

作者给的信息（可能不全，空着的由你补，补的部分在 ai_filled 里列出字段名）：
- 来历类型：$oc_type
- 名字：$oc_name
- 作者描述：$brief
- 切入时间点（原著事件）：$entry_event
- 作者的想法：$idea

原著世界与力量体系（主角的能力不能越过这里的上限）：
$world

原著主要人物：
$characters

要求：
- 主角是爽文主角：主动、有目标、敢出手；能力有明确的上限和成长路线，不要靠自残式代价制造紧张，紧迫感来自原著反派和困境。
- 能力和成长必须在原著力量体系之内：起点不越过切入时间点原著主角的水平，成长节奏要能对上原著时间线。
- 写清他想接触的原著人物（2–4 个）和初始关系，关系要符合那些原著人物在切入时间点的性格和处境。
- 说话方式要和原著角色区分开，一眼看出是谁在说话。

严格只输出 JSON：
{"name":"","summary":"一两句话","data":{"role":"protagonist","origin":"oc","oc_type":"","identity":"在原著世界里的身份",
 "ability":"能力与用法","limit":"现阶段上限","growth":"成长路线","goal":"他想做成的事","voice":"说话方式",
 "personality":"","contacts":[{"name":"原著人物","relation":"初始关系"}],"entry_event":""},
 "ai_filled":["补了哪些字段"]}
