为下面这本书建立设定库。

书名：$title
题材：$genre（$gender_label）
核心设定：$premise

严格只输出 JSON：
{"tagline":"一句话卖点",
 "cards":[{"type":"world|cheat|power|faction|character|item|location","name":"","summary":"",
   "data":{},"known_by":[]}],
 "facts":[{"entity":"卡片名","key":"","value":"","visibility":"author|reader"}]}
要求：至少 1 张 world、1 张 cheat（主角的金手指，data 含 input/limit/growth）、1 张 power（世界通用的力量体系，data 含 levels 境界划分）、2 张 faction、5 张 character（第一张是主角，data 含 role、voice、catchphrases、habits、demeanor、knows、unknown、misbelief）、2 张 item、3 张 location（第一卷会去的地方，data 含 sensory）。设定只铺到第一卷够用，后面的人物、地点在写正文时再登记。
