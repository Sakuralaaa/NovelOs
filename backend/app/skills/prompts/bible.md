为下面这本书建立设定库。

书名：$title
题材：$genre（$gender_label）
核心设定：$premise

严格只输出 JSON：
{"tagline":"一句话卖点",
 "cards":[{"type":"world|power|faction|character|item|location","name":"","summary":"",
   "data":{},"known_by":[]}],
 "facts":[{"entity":"卡片名","key":"","value":"","visibility":"author|reader"}]}
要求：至少 1 张 world、1 张 power（data 含 input/cost/limit）、1 张 faction、3 张 character（第一张是主角，data 含 role、voice、catchphrases、habits、demeanor、knows、unknown、misbelief）、1 张 item、1 张 location（data 含 sensory）。
