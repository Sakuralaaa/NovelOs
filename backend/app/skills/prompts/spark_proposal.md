根据作者抽卡定下的内容，写一份番茄长篇网文（目标 200 万字）的立项书。

基本信息：频道 $gender_label；赛道 $track；细分 $sub；标签 $tags
作者的灵感：$inspiration
世界观：$world
主角：$hero
金手指：$cheat

要求：
- titles：9 个候选书名，番茄式大白话，带身份、数字或情绪钩子，8–15 字为主。
- tagline 一句话卖点；logline 两三句故事梗概；hook 第一章的钩子；selling_points 3–5 个卖点；expectations 读者长期期待；endgame 终局目标；arc 4–6 个长线阶段。
- style：文风标准（句长、节奏、爽点密度、对话比例），一两句话。
- conflict：核心冲突，紧迫感来自反派和困境。
- power：力量体系 {name, levels[]}，levels 5–9 个。
- seed_cards：种子设定卡，至少包含 world、cheat（data 含 input 用法 / limit 上限 / growth 成长线）、power（data.levels）、主角 character（data.role="protagonist"，data.voice 说话方式），以及 1–2 个主要反派。

严格只输出 JSON：
{"titles":[],"tagline":"","logline":"","hook":"","selling_points":[],"expectations":[],"endgame":"","arc":[],"style":"","conflict":"",
 "power":{"name":"","levels":[]},"seed_cards":[{"type":"","name":"","summary":"","data":{}}]}
