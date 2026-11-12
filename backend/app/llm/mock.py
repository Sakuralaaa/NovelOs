"""内置 mock 渠道：确定性、像样的中文假内容。

同样的输入（task + meta）总是得到同样的输出；结构化任务返回合法 JSON 字符串，
正文任务返回成段的中文场景文字（末场景附 ---CHANGES---）。
mock 故意在初稿里留下少量“AI 腔/裸对白/概述句”，好让 lint、审稿、定点重写、精修整条链路都能被演示和测试。
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from typing import Any

from app.lint.banned_zh import PLAIN_REPLACEMENTS, SUMMARY_MARKERS


def _rng(task: str, meta: dict[str, Any], *keys: str) -> random.Random:
    basis = task + "|" + "|".join(str(meta.get(k, "")) for k in keys)
    return random.Random(int(hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16], 16))


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------- 题材素材

KITS: dict[str, dict[str, Any]] = {
    "urban": {
        "world": ("灰港城", "沿海老城，旧码头与新城区隔着一条江，地下钱庄和拳馆把持着夜里的生意。"),
        "power": ("账簿系统", "能看见别人欠下的“人情账”，催收成功即可提取对方一项本事。",
                  {"input": "当面说出对方欠下的一笔账", "cost": "消耗催债值，催回的越多下次能催的额度越大", "limit": "对方不认账时无效；同一人一月只能催一次"}),
        "faction": ("江北钱家", "做地下钱庄起家，明面上开连锁典当行。"),
        "item": ("铜扣账本", "父亲留下的旧账本，铜扣上有一道被刀砍过的豁口。"),
        "location": ("老码头七号仓", "仓顶漏雨，铁皮被锈蚀出一排小洞。", "柴油味混着鱼腥，铁皮被雨点砸得咚咚响"),
        "villain": "钱少坤", "ally": "老周", "city": "灰港城",
        "sensory": ["柴油味混着鱼腥", "铁皮屋顶被雨点砸得咚咚响", "日光灯管嗡嗡地闪", "江风从门缝里往里灌，带着一股潮霉"],
    },
    "xuanhuan": {
        "world": ("九霄界", "宗门林立，以灵根定贵贱，凡人城池依附宗门纳贡。"),
        "power": ("逆脉诀", "以经脉逆行吞炼他人残留的灵力，越级出手。",
                  {"input": "接触对方刚施展过的灵力残痕", "cost": "每日次数有限，随境界提升增加", "limit": "只对同阶上下一境有效；对阵法无效"}),
        "faction": ("青冥宗", "附近三城的宗主门派，外门弟子横行。"),
        "item": ("断纹玉佩", "母亲留下的玉佩，裂纹里嵌着一线暗金。"),
        "location": ("外门杂役院", "院墙低矮，柴房挨着药渣坑。", "药渣发酵的酸苦味，劈柴声一下一下地闷响"),
        "villain": "韩烈", "ally": "哑叔", "city": "落枫城",
        "sensory": ["药渣发酵的酸苦味", "檐角铜铃被山风吹得乱响", "青石板上结了一层薄霜，踩上去咯吱作响", "香炉里的灰还温着"],
    },
    "suspense": {
        "world": ("雾川县", "常年起雾的山城，老街里每隔几年就有人失踪。"),
        "power": ("回声", "触碰死者遗物能听见对方最后十秒听到的声音。",
                  {"input": "赤手触碰遗物", "cost": "需要静心片刻，等级越高听得越久越清楚", "limit": "遗物离开死者超过七天就听不到"}),
        "faction": ("县刑侦大队", "人手不足，上头只想把案子结掉。"),
        "item": ("缺齿钥匙", "失踪者口袋里的钥匙，第三个齿被磨平了。"),
        "location": ("雾川老街", "青砖路，路灯坏了一半。", "潮湿的煤烟味，远处有狗在叫"),
        "villain": "无面人", "ally": "何队", "city": "雾川县",
        "sensory": ["潮湿的煤烟味", "楼道里的声控灯迟迟不亮", "铁门把手冰得扎手", "窗外的雾把路灯晕成一团黄"],
    },
    "romance": {
        "world": ("海城上流圈", "几大家族联姻盘根错节，体面背后全是账。"),
        "power": ("前世记忆", "重生回到订婚宴前一夜，记得之后三年的关键事件。",
                  {"input": "提前布局改变事件", "cost": "改变越大，前世记忆里后面的事越可能变样，需要重新打听", "limit": "记忆只到三年后她死的那一天"}),
        "faction": ("沈家", "女主本家，继母掌着家里的公司。"),
        "item": ("蓝钻胸针", "生母的遗物，被继母拿去给妹妹戴。"),
        "location": ("沈家老宅", "三层小楼，楼梯是老柚木。", "楼梯木板吱呀一声，香槟塔上的气泡细细地往上冒"),
        "villain": "沈薇", "ally": "陆衍", "city": "海城",
        "sensory": ["香槟塔里气泡往上冒", "高跟鞋踩在大理石上一声比一声脆", "空调的冷风贴着裸露的手臂吹", "玫瑰的香气浓得发腻"],
    },
    "palace": {
        "world": ("大胤后宫", "皇帝多疑，太后与皇后两派明争暗斗。"),
        "power": ("辨香", "能从香气里辨出药材与毒物，连人身上残留的味道也能分辨。",
                  {"input": "近身闻到气味", "cost": "连续使用会疲惫，歇一晚就恢复", "limit": "混入浓香后难以分辨；对无味之毒无效"}),
        "faction": ("长春宫", "皇后所居，宫人多是皇后母家送来的。"),
        "item": ("银簪", "入宫时母亲塞给她的银簪，簪头能拧开。"),
        "location": ("浣衣局", "院里晾着成排的宫衣，井水冰凉。", "皂角的涩味，井绳磨着辘轳吱嘎作响"),
        "villain": "柳贵人", "ally": "春桃", "city": "京城",
        "sensory": ["皂角的涩味", "宫灯的烛芯噼啪一声", "炭盆里的银霜炭只剩一点红", "檐下的冰棱滴着水"],
    },
}


def kit_for(genre: str, gender: str = "male") -> dict[str, Any]:
    g = genre or ""
    if re.search(r"玄幻|仙侠|修仙|修真|武侠|宗门", g):
        return KITS["xuanhuan"]
    if re.search(r"悬疑|灵异|诡|推理|刑侦", g):
        return KITS["suspense"]
    if re.search(r"宫|宅|古言|古代", g):
        return KITS["palace"]
    if re.search(r"豪门|总裁|现言|甜宠|重生|女频", g) or gender == "female":
        return KITS["romance"]
    return KITS["urban"]


MALE_NAMES = ["林照", "陈野", "沈砚", "江烬", "顾川"]
FEMALE_NAMES = ["沈栀", "苏晚", "温念", "姜梨", "林知夏"]


def protagonist_name(title: str, gender: str) -> str:
    pool = FEMALE_NAMES if gender == "female" else MALE_NAMES
    h = int(hashlib.md5(title.encode("utf-8")).hexdigest()[:6], 16)
    return pool[h % len(pool)]


# ---------------------------------------------------------------- 选题

IDEA_PATTERNS_M = [
    ("{cat}：我的{power}能催收人情债", "被赶出家门的{who}，发现能把别人欠下的人情变成自己的本事，代价是每用一次就失去痛觉。"),
    ("开局被退婚，我反手掀了{place}", "{who}在退婚宴上被当众羞辱，却握着一本能让全城大佬低头的旧账。"),
    ("{cat}：三天后，全城都在找我", "{who}只有三天时间洗清罪名，唯一的线索在一个死人身上。"),
    ("我在{place}捡属性，越捡越离谱", "{who}每天能从废弃物里捡到一条属性，但捡到的东西都有前主人。"),
]
IDEA_PATTERNS_F = [
    ("重生订婚宴，我把渣男让给了妹妹", "{who}重生回订婚前夜，这一次她要亲手拆掉继母布了十年的局。"),
    ("{cat}：离婚后，前夫跪求复合", "隐忍三年的{who}签下离婚协议，转身拿回被夺走的公司和名字。"),
    ("我在{place}靠闻香破案", "被贬去{place}的{who}能闻出毒物，一桩桩旧案把她推向后宫最深处。"),
    ("{cat}：真千金回府第一天就掀桌", "流落乡下十八年的{who}被接回豪门，所有人都等着看她出丑。"),
]
WHO_M = ["落魄赘婿", "外门杂役", "退役保安", "夜班法医", "穷小子"]
WHO_F = ["假千金", "替嫁新娘", "浣衣宫女", "过气女星", "豪门弃妇"]
PLACE = ["灰港城", "外门", "雾川县", "浣衣局", "沈家老宅", "旧码头"]


def mock_ideation(meta: dict[str, Any]) -> str:
    rng = _rng("ideation", meta, "count", "gender", "genre", "seed")
    gender = meta.get("gender") or "male"
    count = int(meta.get("count") or 3)
    trends = meta.get("trends") or []
    cats = [t.get("category") for t in trends if t.get("category")] or [meta.get("genre") or ("都市高武" if gender == "male" else "现言甜宠")]
    pats = IDEA_PATTERNS_F if gender == "female" else IDEA_PATTERNS_M
    who = WHO_F if gender == "female" else WHO_M
    ideas = []
    for i in range(count):
        cat = meta.get("genre") or cats[i % len(cats)]
        t, l = pats[(i + rng.randint(0, 3)) % len(pats)]
        w, p = rng.choice(who), rng.choice(PLACE)
        kit = kit_for(cat, gender)
        title = t.format(cat=cat, power=kit["power"][0], place=p)
        ideas.append({
            "title": title,
            "logline": l.format(who=w, place=p),
            "selling_points": [
                f"开局即冲突：{w}被当众踩到脚下，第一章就反击",
                f"金手指越用越强：{kit['power'][0]}每升一级都能解锁新用法",
                f"身份反差：所有人看不起的{w}，握着{kit['item'][0]}的秘密",
            ],
            "hook": f"第一章三百字内，{w}在{p}被人堵住，对方要他交出{kit['item'][0]}。",
            "expectations": ["金手指一级级解锁", "查清开局那场变故的真相"],
            "endgame": f"揭开{kit['item'][0]}的来历，站到这个世界的最顶端",
            "arc": [f"在{p}站稳脚跟，收下第一批班底", "走出小地方，压服一州的世家与宗门", "卷入王朝之争，与幕后势力正面交锋", "打进上层世界，直面金手指背后的旧秩序"],
            "genre": cat,
            "novelty": rng.randint(55, 88),
            "fit": rng.randint(60, 92),
        })
    return _j({"ideas": ideas})


def mock_idea_revise(meta: dict[str, Any]) -> str:
    out = {k: meta.get(k) for k in ("title", "logline", "selling_points", "hook", "expectations", "endgame", "arc", "genre")}
    note = str(meta.get("instruction") or "")[:20]
    out["logline"] = f"{out.get('logline') or ''}（已按“{note}”调整）"
    out.update({"novelty": 70, "fit": 75, "change": f"按“{note}”调整了简介"})
    return _j(out)


def mock_idea_score(meta: dict[str, Any]) -> str:
    n = int(meta.get("count") or 1)
    keys = ("gf", "angle", "fresh", "opening", "payoff", "growth", "longrun", "pitch")
    return _j({"scores": [{"index": i, **{k: max(0, min(4, 4 - (i - 1) % 4 + j % 3 - 1)) for j, k in enumerate(keys)}, "issue": "爽点兑现偏慢" if i == 2 else "无"} for i in range(1, n + 1)]})


def mock_idea_field(meta: dict[str, Any]) -> str:
    cur = meta.get("current")
    note = str(meta.get("instruction") or "改写")[:12]
    if isinstance(cur, list):
        return _j({"value": [f"{x}（{note}）" for x in cur] or [note]})
    return _j({"value": f"{cur}（{note}）"})


def mock_cover_prompt(meta: dict[str, Any]) -> str:
    return _j({"prompt": f"{meta.get('current') or '主角立于高处'}。{meta.get('instruction') or ''}".strip()})


def mock_card_suggest(meta: dict[str, Any]) -> str:
    note = str(meta.get("instruction") or "改写")[:12]
    cur = meta.get("current")
    if meta.get("field"):
        if isinstance(cur, list):
            return _j({"value": [*cur, note]})
        return _j({"value": f"{cur or ''}（{note}）"})
    card = dict(cur or {})
    card["summary"] = f"{card.get('summary') or ''}（{note}）"
    card["name"] = card.get("name") or "新人物"
    return _j({"card": card})


# ---------------------------------------------------------------- 设定

def mock_bible(meta: dict[str, Any]) -> str:
    title = meta.get("title") or "未命名"
    gender = meta.get("gender") or "male"
    kit = kit_for(meta.get("genre") or "", gender)
    p = meta.get("protagonist") or protagonist_name(title, gender)
    pro = "她" if gender == "female" else "他"
    cards = [
        {"type": "world", "name": kit["world"][0], "summary": kit["world"][1], "data": {"era": "架空", "rules": ["强者守规矩，弱者交保护费", "账可以赖，但不能当众赖"]}, "known_by": []},
        {"type": "cheat", "name": kit["power"][0], "summary": kit["power"][1], "data": {**kit["power"][2], "growth": "每升一级解锁一种新用法"}, "known_by": [p]},
        {"type": "power", "name": "境界", "summary": "这个世界通行的修炼等级。", "data": {"levels": "淬体、通脉、凝元、化神"}, "known_by": []},
        {"type": "faction", "name": kit["faction"][0], "summary": kit["faction"][1], "data": {"leader": kit["villain"], "stance": "敌对"}, "known_by": []},
        {"type": "character", "name": p, "summary": f"主角。表面隐忍，{pro}记仇，也记恩。", "data": {
            "role": "protagonist", "voice": "话少，句子短而硬，不解释，只给结论", "catchphrases": ["账得算清楚。"],
            "habits": ["说话前先把袖口往上挽一道", "想事时用拇指摩挲指节上的旧疤"], "demeanor": "不动声色，越生气越安静",
            "knows": [f"{kit['item'][0]}和父母的死有关"], "unknown": [f"{kit['ally']}的真实身份"], "misbelief": [f"以为{kit['villain']}是仇人本人"],
        }, "known_by": [kit["ally"]]},
        {"type": "character", "name": kit["ally"], "summary": "看着主角长大的老人，嘴硬心软，身上有旧伤。", "data": {
            "role": "ally", "voice": "爱用反问，絮叨，带点方言腔", "catchphrases": ["你当我老糊涂了？"],
            "habits": ["摸出半截烟又塞回去", "一着急就拍大腿"], "demeanor": "眯眼看人，笑起来露出缺了的门牙",
        }, "known_by": []},
        {"type": "character", "name": kit["villain"], "summary": f"{kit['faction'][0]}的少主，傲慢，手段脏。", "data": {
            "role": "antagonist", "voice": "慢条斯理，喜欢用敬语羞辱人", "catchphrases": ["给你脸了？"],
            "habits": ["转着手上的扳指", "说话时不看人，看自己的指甲"], "demeanor": "笑着，眼睛不笑",
        }, "known_by": []},
        {"type": "item", "name": kit["item"][0], "summary": kit["item"][1], "data": {"owner": p}, "known_by": [p]},
        {"type": "location", "name": kit["location"][0], "summary": kit["location"][1], "data": {"sensory": kit["location"][2]}, "known_by": []},
    ]
    facts = [
        {"entity": p, "key": "处境", "value": "被所有人看不起，身无分文", "visibility": "reader"},
        {"entity": kit["item"][0], "key": "下落", "value": f"在{p}手里", "visibility": "reader"},
        {"entity": kit["ally"], "key": "真实身份", "value": f"曾是{kit['faction'][0]}的老账房", "visibility": "author"},
    ]
    return _j({"tagline": f"{p}握着一本旧账，要{kit['city']}所有欠债的人一个个还回来。", "cards": cards, "facts": facts})


# ---------------------------------------------------------------- 大纲

CH_TEMPLATES: list[dict[str, str]] = [
    {"title": "夜雨堵门", "goal": "在{loc}拿回被扣下的{item}", "conflict": "{villain}带人堵门，当众羞辱{p}", "outcome": "no-and",
     "payoff": "{p}挨了一记耳光，却当场记下{villain}的一笔账", "hook_end": "{villain}的人把{item}砸在地上，{p}弯腰去捡，看见裂口里透出一线光"},
    {"title": "第一笔账", "goal": "第一次用{power}催回一笔人情", "conflict": "对方翻脸不认，{ally}劝{p}别惹事", "outcome": "yes-but",
     "payoff": "{p}一句话让对方当众认账，借{power}拿走了对方的本事", "hook_end": "{p}发现自己被刀划开的手掌，一点也不疼"},
    {"title": "当众结账", "goal": "在{villain}的场子上讨回公道", "conflict": "{villain}请来了帮手，要{p}跪着出去", "outcome": "yes",
     "payoff": "{p}用刚得来的本事碾压帮手，{villain}的人全看傻了", "hook_end": "人群后面，一个戴斗笠的人冲{p}点了点头，转身就走"},
    {"title": "旧账房", "goal": "弄清{item}上那道豁口的来历", "conflict": "{ally}支支吾吾，像在躲什么", "outcome": "no",
     "payoff": "{p}从{ally}的反应里看出端倪，没有逼问", "hook_end": "{ally}半夜出门，往{faction}的方向去了"},
    {"title": "跟踪", "goal": "跟上{ally}，看他见谁", "conflict": "{faction}的暗哨发现了{p}", "outcome": "no-and",
     "payoff": "{p}甩掉暗哨，反手摸清了对方一处据点", "hook_end": "据点墙上挂着一张照片，照片上是年轻时的{ally}"},
    {"title": "设局", "goal": "让{villain}主动来找{p}", "conflict": "{villain}也在设局，想引{p}入套", "outcome": "yes-but",
     "payoff": "{villain}以为抓住了{p}的把柄，当众亮牌，却正中下怀", "hook_end": "{p}收到一条消息：你父亲没死"},
    {"title": "对赌", "goal": "和{villain}对赌，赢回{loc}", "conflict": "赌局被做了手脚", "outcome": "yes",
     "payoff": "{p}当场拆穿出千，{villain}输掉{loc}，脸色铁青", "hook_end": "{faction}的家主亲自打来电话，只说了一句：明天见"},
    {"title": "家主", "goal": "在{faction}家主面前保住命", "conflict": "家主要{p}交出{item}", "outcome": "no",
     "payoff": "{p}一句旧账让家主变了脸色", "hook_end": "家主说出{ally}的真名"},
    {"title": "反咬", "goal": "护住{ally}", "conflict": "{villain}反咬一口，{ally}被带走", "outcome": "no-and",
     "payoff": "{p}忍住没出手，把{villain}的罪证一份份收好", "hook_end": "{p}摸到{item}在发烫，{villain}的名字浮在上面"},
    {"title": "清算", "goal": "当众清算{villain}", "conflict": "{villain}拿{ally}做人质", "outcome": "yes",
     "payoff": "{p}一笔一笔念出{villain}欠下的账，对方的手下一个个倒戈", "hook_end": "{item}上浮出一个更大的名字"},
]


def _fill(s: str, ctx: dict[str, str]) -> str:
    return s.format(**ctx)


def _ctx(meta: dict[str, Any]) -> dict[str, str]:
    kit = kit_for(meta.get("genre") or "", meta.get("gender") or "male")
    return {
        "p": meta.get("protagonist") or protagonist_name(meta.get("title") or "", meta.get("gender") or "male"),
        "villain": meta.get("villain") or kit["villain"], "ally": meta.get("ally") or kit["ally"],
        "item": meta.get("item") or kit["item"][0], "loc": meta.get("location") or kit["location"][0],
        "power": kit["power"][0], "faction": kit["faction"][0], "city": kit["city"],
    }


def chapter_beats(number: int, meta: dict[str, Any]) -> dict[str, Any]:
    ctx = _ctx(meta)
    t = CH_TEMPLATES[(number - 1) % len(CH_TEMPLATES)]
    cycle = (number - 1) // len(CH_TEMPLATES)
    beats: dict[str, Any] = {k: _fill(v, ctx) for k, v in t.items()}
    if cycle:
        beats["title"] = f"{beats['title']}（{['其二', '其三', '其四', '其五'][min(cycle - 1, 3)]}）"
    chars = [ctx["p"]]
    if number % 2 == 1 or "{villain}" in t["conflict"]:
        chars.append(ctx["villain"])
    if "{ally}" in t["conflict"] or "{ally}" in t["goal"] or number % 3 == 2:
        chars.append(ctx["ally"])
    beats["characters"] = list(dict.fromkeys(chars))
    beats["location"] = ctx["loc"]
    fs: list[dict[str, Any]] = []
    if number == 1:
        fs.append({"action": "plant", "id": None, "desc": f"{ctx['item']}上的豁口"})
    if number == 2:
        fs.append({"action": "plant", "id": None, "desc": f"{ctx['ally']}隐瞒的过去"})
    if number == 4:
        fs.append({"action": "advance", "id": None, "desc": f"{ctx['ally']}隐瞒的过去"})
    if number == 5:
        fs.append({"action": "advance", "id": None, "desc": f"{ctx['item']}上的豁口"})
    if number == 8:
        fs.append({"action": "resolve", "id": None, "desc": f"{ctx['ally']}隐瞒的过去"})
    beats["foreshadow"] = fs
    beats["number"] = number
    return beats


def mock_outline(meta: dict[str, Any]) -> str:
    ctx = _ctx(meta)
    per_arc = int(meta.get("chapters_per_arc") or 5)
    volumes = [
        {"title": f"第一卷 {ctx['city']}旧账", "summary": f"卷目标：{ctx['p']}在{ctx['city']}站稳脚跟，扳倒{ctx['villain']}。"},
        {"title": f"第二卷 {ctx['faction']}", "summary": f"卷目标：查清{ctx['item']}背后的旧案，正面对上{ctx['faction']}家主。"},
        {"title": "第三卷 总账", "summary": f"卷目标：{ctx['p']}把二十年前的那本总账，当着所有人的面翻开。"},
    ]
    arcs = []
    n = 1
    for ai, (title, summ) in enumerate([("夜雨堵门", f"{ctx['p']}被逼到绝路，第一次催回人情债。"),
                                        ("旧账房", f"{ctx['ally']}的过去浮出水面，{ctx['villain']}开始设局。")]):
        chs = []
        for _ in range(per_arc):
            chs.append(chapter_beats(n, meta))
            n += 1
        arcs.append({"volume": 1, "title": f"第{ai + 1}弧 {title}", "summary": summ, "chapters": chs})
    return _j({"book": {"title": meta.get("title") or "未命名", "summary": f"{ctx['p']}握着一本旧账，从{ctx['city']}最底层一路算到最高处。"},
               "volumes": volumes, "arcs": arcs})


def mock_expand(meta: dict[str, Any]) -> str:
    level = meta.get("level")
    if level == "book":
        ctx = _ctx(meta)
        start = int(meta.get("existing") or 0)
        return _j({"volumes": [{"title": f"第{start + i + 1}卷 新的账", "summary": f"卷目标：{ctx['p']}把账算到更高的地方。"} for i in range(2)]})
    if level == "volume":
        start = int(meta.get("existing") or 0)
        return _j({"arcs": [{"title": f"第{start + i + 1}弧 {['暗流', '对峙', '翻盘'][(start + i) % 3]}", "summary": "新的对手入场，旧账牵出新账。"} for i in range(2)]})
    if level == "arc":
        first = int(meta.get("next_number") or 1)
        per = int(meta.get("chapters_per_arc") or 5)
        return _j({"chapters": [chapter_beats(first + i, meta) for i in range(per)]})
    number = int(meta.get("number") or 1)
    return _j({"beats": chapter_beats(number, meta)})


# ---------------------------------------------------------------- 场景节拍

OUTCOMES = ["yes", "no", "yes-but", "no-and"]


def mock_scene_plan(meta: dict[str, Any]) -> str:
    beats = meta.get("beats") or {}
    rng = _rng("scene_plan", meta, "number")
    sensory = meta.get("sensory_pool") or ["雨水顺着屋檐往下淌", "灯管嗡嗡地闪"]
    chars = beats.get("characters") or [meta.get("protagonist") or "主角"]
    p = chars[0]
    n_scenes = 4 if int(meta.get("words") or 2200) >= 1800 else 3
    final = beats.get("outcome") or "yes-but"
    plan = [
        {"goal": beats.get("goal", "达成本章目标"), "conflict": "有人挡在前面，不让" + p + "进门", "outcome": "no", "characters": chars[:2], "sensory": sensory[0 % len(sensory)]},
        {"goal": "试探对方的底牌", "conflict": beats.get("conflict", "对手施压"), "outcome": "yes-but", "characters": chars, "sensory": sensory[1 % len(sensory)]},
        {"goal": "抓住对方的破绽", "conflict": "对方先一步动手", "outcome": "no-and" if final != "no-and" else "yes-but", "characters": chars, "sensory": sensory[2 % len(sensory)]},
        {"goal": "收下这一局的结果", "conflict": "局面急转", "outcome": final, "characters": chars, "sensory": sensory[3 % len(sensory)]},
    ][:n_scenes]
    rng.shuffle(plan[1:-1])
    return _j({"scenes": plan})


# ---------------------------------------------------------------- 正文

P_ACTIONS = [
    "把袖口往上挽了一道，指尖蹭过腕上那条旧疤",
    "往前走了半步，鞋底碾过地上的碎瓷片，咯吱一声",
    "把那张皱巴巴的单据拍在桌上，用两根手指按住一角",
    "侧身让开递过来的手，顺势把门带上，门轴发出一声干涩的响",
    "弯腰捡起地上的烟盒，捏扁了，丢进墙角的铁皮桶",
    "拉开椅子坐下，椅腿在地上刮出一道刺耳的声音",
    "把湿透的外套脱下来搭在椅背上，水顺着衣角滴了一地",
    "抬手把挡在眼前的灯罩推开，灯晃了两晃，屋里的影子跟着乱晃",
    "从怀里摸出那样东西，在掌心掂了掂，又揣回去",
    "把桌上翻倒的茶碗扶正，顺手抹掉桌面上的一圈水渍",
]
P_LINES = [
    "东西我会拿走，账也会一笔一笔算清楚。",
    "你说完了？那轮到我了。",
    "三天太长了，今晚就够。",
    "我来，是给你留条活路的。",
    "别急，等会儿有你说话的时候。",
    "这一下我记着，连本带利。",
    "你手底下这些人，有几个是真心跟你的，你自己心里没数？",
    "去年腊月十七，你在哪儿，见了谁，要我替你说吗？",
    "门开着，想走的现在走，我不拦。",
    "我只问一遍，东西在哪儿。",
]
A_LINES = [
    "这地方不是你该来的，趁我还好说话，自己走。",
    "东西交出来，今天的事我当没看见。",
    "你以为换了身衣服，就没人认得你了？",
    "规矩是我定的，想坏规矩，先问问我身后这些兄弟答不答应。",
    "听说你最近很能耐，连我的人都敢动？",
    "跪下，磕三个头，我让你从正门出去。",
    "你爹欠的账，轮得到你来算？",
    "给你脸了？在这儿，我说的话就是规矩。",
    "行啊，你开个价，我倒想听听你值多少。",
]
ALLY_LINES = [
    "你当我老糊涂了？那帮人是你惹得起的？",
    "听叔一句，先忍着，东西跑不了。",
    "我早跟你说过，这条街上的事，没那么简单。",
    "你要真想好了，叔给你望风，可你得答应我，见势不对就跑。",
]
GENERIC_LOOKS = [
    "眼皮都没抬，手指在桌面上敲了两下",
    "上下打量了一遍，目光在沾泥的鞋尖上停了停",
    "把茶碗往桌上一磕，茶水溅出来几滴，洇湿了桌布",
    "靠在门框上，嘴里叼着的烟一明一灭",
    "往椅背上一靠，两条腿架到桌沿上",
    "把手里的核桃捏得咯咯响，半天没吭声",
]
ENV_BEATS = [
    "灯管嗡嗡地响", "外头雨点砸在铁皮上", "有人咽口水的声音", "炭盆里的火噼啪一声", "墙上的挂钟走得很响",
    "楼上有人拖着凳子走", "远处的狗叫了两声又停了",
]
# 每个模板一段，互不重复；{la} 对手台词，{lp} 主角台词
FILLERS = [
    "{a}{look}，半晌才憋出一句：“{la}”",
    "{p}{act}，声音压得很平：“{lp}”",
    "屋里没人接话。{p}看见{a}的手下往门口挪了一步，把退路堵上，{pro}也不急，{act}。",
    "“{la}”{a}说着往前凑，一股酒气跟着扑过来。{p}没退，等那股气味散了，才抬眼看{a}。",
    "{p}把这句话在嘴里过了一遍，没有马上回。{pro}{act}，等到{env}，才开口：“{lp}”",
    "{a}的笑僵在脸上。{pro2}身后那个年轻的先沉不住气，骂了一句脏话，被{a}抬手拦下了。",
    "“{lp}”{p}说完，把东西往桌上一放。桌面不平，那东西晃了两下才停住，满屋子的眼睛都跟着它晃。",
    "{a}{look}，过了好一阵，忽然笑出声来：“{la}”笑声在屋里撞了一圈，没人跟着笑。",
    "{p}注意到{a}说话时一直没看自己，看的是门外。外头有什么，{pro}不知道，但{pro}记下了。",
    "{env}。{p}趁这个空当把屋里的人又数了一遍，比进门时多了两个，都站在灯照不到的地方。",
    "“{la}”这话一出，旁边几个人都低下头去。{p}{act}，像是根本没听见。",
    "{p}没再说话。{pro}把手按在桌沿上，指腹底下是一道一道的刀痕，不知道是谁、哪一年刻上去的。",
]
OUTCOME_LINES = {
    "yes": "{p}把东西揣进怀里，转身往外走。身后没有人追上来，只有那盏灯还在晃，把满屋子的人影晃得东倒西歪。",
    "no": "门在{p}面前合上了，门闩落下的声音很重。{p}在台阶上站了一会儿，雨水顺着后颈往衣领里钻，凉得发麻，{pro}没动，把刚才每个人说的话在心里又过了一遍。",
    "yes-but": "{p}拿到了想要的东西，手背却被划开一道口子，血顺着指缝往下滴，{pro}低头看了一眼，竟然一点也不觉得疼。",
    "no-and": "{p}还没站稳，后脑就挨了一下，眼前一黑，耳边只剩下雨点砸铁皮的声音，和有人凑过来时那股呛人的烟味。",
}


def _voice(meta: dict[str, Any], name: str) -> dict[str, Any]:
    return (meta.get("voices") or {}).get(name) or {}


def _habit(meta: dict[str, Any], name: str, rng: random.Random) -> str:
    v = _voice(meta, name)
    habits = v.get("habits") or []
    return rng.choice(habits) if habits else rng.choice(GENERIC_LOOKS)


def _deck(rng: random.Random, items: list[str]) -> list[str]:
    d = list(items)
    rng.shuffle(d)
    return d


def mock_writing_scene(meta: dict[str, Any]) -> str:
    beats = meta.get("beats") or {}
    scene = meta.get("scene") or {}
    p = meta.get("protagonist") or "林照"
    pro = meta.get("pronoun") or "他"
    idx = int(meta.get("scene_index") or 1)
    total = int(meta.get("scene_total") or 1)
    number = int(meta.get("number") or 1)
    variant = int(meta.get("variant") or 0)
    # 章级洗牌：同一章内各场景从同一副“牌”里按段取，避免重复
    deck_rng = random.Random(f"{meta.get('title')}|{number}|{variant}")
    acts, lps, las, envs, fillers = (_deck(deck_rng, x) for x in (P_ACTIONS, P_LINES, A_LINES, ENV_BEATS, FILLERS))
    rng = _rng("writing_scene", meta, "number", "scene_index", "variant", "title")
    k = (idx - 1) * 3

    def take(d: list[str], j: int) -> str:
        return d[(k + j) % len(d)]

    loc = beats.get("location") or "屋里"
    sensory = scene.get("sensory") or "雨点砸在铁皮屋顶上"
    others = [c for c in (scene.get("characters") or beats.get("characters") or []) if c != p]
    villain = meta.get("villain") or (others[0] if others else "那人")
    a = others[(idx - 1) % len(others)] if others else villain
    ally = meta.get("ally") or ""
    a_lines = ALLY_LINES if a == ally else las
    words = int(meta.get("scene_words") or 550)
    a_look = _habit(meta, a, rng)

    paras: list[str] = []
    if idx == 1:
        paras.append(
            f"{p}{rng.choice(['推开', '撞开', '掀开'])}{loc}那扇半掩的门，{sensory}，扑了{pro}一脸。"
            f"{pro}在门口站定，先把屋里的人数了一遍，又看了看他们脚边的家伙，才抬脚往里走。"
        )
        paras.append(f"{pro}今天来，只为一件事：{beats.get('goal', '把东西拿回来')}。晚一步，这件事就再也办不成了。")
    else:
        paras.append(f"{sensory}。{p}{take(acts, 0)}，{scene.get('goal', '')}这件事，{pro}在路上已经想过三遍。")

    paras.append(f"{a}{a_look}，开口时连看都没看{p}：“{a_lines[(k) % len(a_lines)]}”")
    cp = (_voice(meta, p).get("catchphrases") or ["账得算清楚。"])[0]
    paras.append(f"{p}没接话，{take(acts, 1)}。“{take(lps, 0)}”{pro}顿了顿，又补了一句，“{cp}”" if idx == 1
                 else f"{p}没接话，{take(acts, 1)}。“{take(lps, 0)}”")
    paras.append(
        f"{scene.get('conflict', beats.get('conflict', ''))}。屋里一下子静了，只听得见{take(envs, 0)}，"
        f"几个人的手都往腰后摸，眼睛却都盯着{a}。"
    )

    # 刻意留下的问题（初稿 variant 0 才有）：供 lint / 审稿 / 定点重写 / 精修演示
    if variant == 0 and idx == 2:
        paras.append(f"“{rng.choice(['你想怎样？', '就凭你？', '说完了？'])}”")
        paras.append(f"“{rng.choice(['你会知道的。', '就凭我。', '还没有。'])}”")
        paras.append("经过一番周旋，事情很快有了结果，于是两人随后各自散开，约定改日再谈。")
    if number % 2 == 1 and idx == 1 and variant == 0:
        paras.append(f"{p}嘴角勾起一抹冷笑，眼中闪过一丝寒意，不禁想起了那一夜。")

    j = 0
    while sum(len(x) for x in paras) < words * 0.85 and j < len(fillers):
        tpl = fillers[(k + j) % len(fillers)]
        j += 1
        paras.append(tpl.format(p=p, a=a, pro=pro, pro2="他", act=take(acts, 2 + j), look=rng.choice(GENERIC_LOOKS),
                                la=a_lines[(k + j) % len(a_lines)], lp=take(lps, j), env=take(envs, j)))
    paras.append(_fill(OUTCOME_LINES.get(scene.get("outcome") or "yes", OUTCOME_LINES["yes"]), {"p": p, "pro": pro}))
    if idx == total:
        paras.append(f"{beats.get('hook_end', '门外传来一阵急促的脚步声')}。")
    text = "\n\n".join(paras)

    if meta.get("include_changes"):
        changes: dict[str, Any] = {"new_entities": [], "state_changes": [], "foreshadow": []}
        if number == 2:
            changes["new_entities"].append({"type": "character", "name": "斗笠客", "summary": "人群后冲主角点头的神秘人，身份未知。"})
        changes["state_changes"].append({"entity": p, "key": "处境", "value": {
            "yes": "占了上风", "no": "吃了闭门羹", "yes-but": "得手但付出代价", "no-and": "受伤落入下风"}.get(beats.get("outcome", "yes"), "局面未定"), "visibility": "reader"})
        for f in beats.get("foreshadow") or []:
            changes["foreshadow"].append({"action": f.get("action"), "id": f.get("id"), "desc": f.get("desc")})
        text += "\n\n---CHANGES---\n" + _j(changes)
    return text


# ---------------------------------------------------------------- 审稿 / 重写 / 精修 / 摘要

def _sentences(content: str) -> list[str]:
    body = content.split("---CHANGES---")[0]
    return [s.strip() for s in re.findall(r"[^。！？\n]+[。！？]", body) if len(s.strip()) >= 6]


def mock_review(meta: dict[str, Any]) -> str:
    content = meta.get("content") or ""
    sents = _sentences(content)
    issues: list[dict[str, str]] = []
    for s in sents:
        if "嘴角勾起一抹" in s:
            issues.append({"severity": "high", "dimension": "character", "quote": s,
                           "comment": "模板化表情，与主角“越生气越安静”的人设冲突，改成具体动作"})
            break
    for s in sents:
        if any(m in s for m in ("经过一番", "很快", "于是", "随后")):
            issues.append({"severity": "mid", "dimension": "pacing", "quote": s, "comment": "概述一句带过，读者看不到场面，展开成可见的动作与对白"})
            break
    if sents:
        issues.append({"severity": "low", "dimension": "hook", "quote": sents[-1], "comment": "章末钩子可以再落到一个具体动作上"})
    # 故意编造一条不在正文里的 quote：程序应当丢弃
    issues.append({"severity": "mid", "dimension": "payoff", "quote": "他一拳打碎了整座山门，众人纷纷跪下。", "comment": "爽点过于夸张"})
    return _j({"issues": issues})


def mock_humanize(meta: dict[str, Any]) -> str:
    content = meta.get("content") or ""
    patches: list[dict[str, str]] = []
    seen: set[str] = set()
    for s in _sentences(content):
        new = s
        for k, v in sorted(PLAIN_REPLACEMENTS.items(), key=lambda kv: -len(kv[0])):
            new = new.replace(k, v)
        if "嘴角" in s and "冷笑" in s:
            who = meta.get("protagonist") or "他"
            new = f"{who}没出声，手指在桌沿上按了一下，把那一夜的事又过了一遍。"
        elif any(m in s for m in ("经过一番", "很快", "于是", "随后")):
            new = "两人又磨了半盏茶的工夫，门外的脚步声来回过了三趟，才各自起身，约好改日再谈。"
        if new != s and s not in seen:
            seen.add(s)
            patches.append({"quote": s, "replacement": new})
        if len(patches) >= 8:
            break
    return _j({"patches": patches})


def mock_thicken(meta: dict[str, Any]) -> str:
    rng = _rng("thicken", meta, "number")
    names = list((meta.get("voices") or {}).keys()) or ["对面的人"]
    p = meta.get("protagonist") or names[0]
    out = []
    for t in meta.get("targets") or []:
        text = str(t.get("text", ""))
        if "“" in text:
            who = rng.choice(names)
            habit = _habit(meta, who, rng)
            new = f"{who}{habit}，过了一会儿才开口：{text}"
        else:
            new = text
            for m in sorted(SUMMARY_MARKERS, key=len, reverse=True):
                new = new.replace(m, "")
            new = (
                f"{p}把话一句一句摊开，对面先是沉着脸听，听到要紧处，手里的茶碗搁下了，碗底磕在桌面上一声轻响。"
                f"两人又磨了半盏茶的工夫，门外的脚步声来回过了三趟，{new.strip('，。')}。"
            )
        out.append({"index": t.get("index"), "text": new})
    return _j({"paragraphs": out})


def mock_summary(meta: dict[str, Any]) -> str:
    beats = meta.get("beats") or {}
    n = meta.get("number") or 1
    outcome = {"yes": "得手", "no": "没能得手", "yes-but": "得手但付出代价", "no-and": "失手且局面更糟"}.get(beats.get("outcome", ""), "局面未定")
    s = (f"第{n}章：{beats.get('goal', '主角推进主线')}。{beats.get('conflict', '')}，结果{outcome}。"
         f"爽点：{beats.get('payoff', '')}。章末：{beats.get('hook_end', '')}。")
    return _j({"summary": s})


def mock_package(meta: dict[str, Any]) -> str:
    ctx = _ctx(meta)
    p = ctx["p"]
    titles = [
        f"开局被退婚，我靠{ctx['power']}杀疯了",
        f"{ctx['city']}：我的账本能催命",
        f"三天后，全{ctx['city'][-1]}都欠我一个人情",
        "被赶出家门后，我成了全城的债主",
        f"{p}的账本",
        f"重回{ctx['city']}，这一次我只收账",
        "我有一本账，专治各种不服",
        "她说我配不上，第二天她爸跪着来还债",
    ]
    blurb = (
        f"雨夜，{p}被{ctx['villain']}的人堵在{ctx['loc']}，被逼着交出父亲留下的{ctx['item']}。\n"
        f"没人知道，那本旧账能让欠债的人当场认账，{p}每催回一笔人情，就能拿走对方一项本事，代价是一段时间里感觉不到疼。\n"
        f"当{ctx['faction']}的家主念出一个早该死去的名字，{p}才发现，自己要算的，是一笔二十年前的总账。"
    )
    tags = [meta.get("genre") or "都市", "逆袭", "系统", "打脸", "复仇"]
    cover = (f"{meta.get('genre') or '都市'}网文封面，竖版 3:4，雨夜老码头，一个年轻人背影站在霓虹与积水之间，"
             f"手里握着一本铜扣旧账本，冷蓝与橙色对比光，厚涂插画风，上半部给书名大字留位置，书名用金属浮雕质感")
    return _j({"titles": titles, "blurb": blurb, "tags": tags[:5], "cover_prompt": cover})


def mock_style_extract(meta: dict[str, Any]) -> str:
    st = meta.get("stats") or {}
    avg = st.get("avg_sentence_len", 0)
    dr = st.get("dialogue_ratio", 0)
    return _j({
        "summary": f"平均句长约 {avg} 字，对话占比约 {dr:.0%}；叙述以连贯动作链推进，对白前后多配手上的动作。",
        "techniques": [
            "同一主语的连续动作写成一个长句，用逗号顺承",
            "关键反转用短句单独成段",
            "环境随人物动作出现，推门才有风",
            "对白不加修饰标签，说话人靠前一句的动作指认",
            "情绪不直说，写手上的物件和身体的停顿",
        ],
        "dialogue_style": "短而有来回，每轮对白之间夹一个推进局势的动作",
        "description_style": "感官细节集中在一两个具体物件上，不铺排风景",
        "avoid": ["概述句", "修饰副词", "翻案腔"],
    })


HANDLERS = {
    "ideation": mock_ideation,
    "idea_revise": mock_idea_revise,
    "idea_field": mock_idea_field,
    "idea_score": mock_idea_score,
    "bible": mock_bible,
    "outline": mock_outline,
    "expand": mock_expand,
    "scene_plan": mock_scene_plan,
    "writing_scene": mock_writing_scene,
    "review": mock_review,
    "humanize": mock_humanize,
    "thicken": mock_thicken,
    "summary": mock_summary,
    "package": mock_package,
    "card_suggest": mock_card_suggest,
    "cover_prompt": mock_cover_prompt,
    "style_extract": mock_style_extract,
}


def complete(task: str, messages: list[dict[str, str]], meta: dict[str, Any]) -> str:
    fn = HANDLERS.get(task)
    if fn is None:
        return _j({"ok": True, "note": "mock"})
    return fn(meta)
