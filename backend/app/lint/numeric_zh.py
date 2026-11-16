"""v0.9.4 数值一致性检查（纯规则，确定性）。

同一对象的同一项数值，同章前后、或与设定卡/事实账本对照不一致时，给出 mid 问题（带位置与原句）：
- 重量：斤 / 公斤 / 千克 / 克 / 吨（统一换算成公斤比较；市制与公制混用另给一条提示）
- 长度/身高：米 / 厘米 / 公分 / 公里 / 千米 / 丈 / 尺 / 寸（“一米八”= 1.8 米）
- 年龄：N 岁（排除“十岁那年”“比他大三岁”这类回忆/相对说法）
- 期限：「三天后的宗门大比」与「后天的宗门大比」（中间写到“第二天/次日/一夜过去”等时间推进时不报）
- 境界：炼气三层 / 筑基二重 / 斗者九星…（同章中间有“突破/晋升/踏入”等不报）
- 机甲/器物参数：高 / 长 / 重 / 功率（千瓦、马力）/ 时速

为控制误报，只比较“能确定对象”的数值：对象 = 属性词前的人名/物名（或句内上一处数值的对象）。
没有属性词、对象不明的数字一律不比较。启发式，阈值与词表为经验值。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# ------------------------------------------------------------------ 中文数字

_DIG = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNIT = {"十": 10, "百": 100, "千": 1000}
NUM = r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+(?:点[零〇一二三四五六七八九]+)?|半)"


def cn_to_num(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    if s == "半":
        return 0.5
    frac = 0.0
    if "点" in s:
        s, f = s.split("点", 1)
        ds = "".join(str(_DIG.get(c, "")) for c in f)
        frac = float("0." + ds) if ds else 0.0
    total, section, cur = 0, 0, 0
    for c in s:
        if c in _DIG:
            cur = _DIG[c]
        elif c in _UNIT:
            section += (cur or 1) * _UNIT[c]
            cur = 0
        elif c == "万":
            total += (section + cur) * 10000
            section, cur = 0, 0
        else:
            return None
    # “一万五”“三百五”这种省略末位单位的说法
    if cur and len(s) >= 2 and s[-2] in "万千百":
        cur *= {"万": 1000, "千": 100, "百": 10}[s[-2]]
    return float(total + section + cur) + frac


# ------------------------------------------------------------------ 单位与属性

UNITS: dict[str, tuple[str, float, str]] = {  # 单位 → (维度, 换算到基准单位的系数, 制式)
    "公斤": ("weight", 1.0, "metric"), "千克": ("weight", 1.0, "metric"), "kg": ("weight", 1.0, "metric"),
    "斤": ("weight", 0.5, "market"), "克": ("weight", 0.001, "metric"), "吨": ("weight", 1000.0, "metric"),
    "厘米": ("length", 0.01, "metric"), "公分": ("length", 0.01, "metric"), "公里": ("length", 1000.0, "metric"),
    "千米": ("length", 1000.0, "metric"), "米": ("length", 1.0, "metric"),
    "丈": ("length", 10 / 3, "market"), "尺": ("length", 1 / 3, "market"), "寸": ("length", 1 / 30, "market"),
    "千瓦": ("power", 1.0, "metric"), "马力": ("power", 0.7355, "metric"),
}
_UNIT_RX = "|".join(sorted(UNITS, key=len, reverse=True))
_MEASURE_RX = re.compile(rf"({NUM})\s*({_UNIT_RX})(?:(?<=米)([一二三四五六七八九])(?![个只层块条根米十百千万]))?")
_AGE_RX = re.compile(rf"({NUM})\s*岁")

# 属性词（决定比较的是哪一项）：长的在前
ATTRS: list[tuple[str, str]] = [
    ("身高", "height"), ("个头", "height"), ("个子", "height"), ("高度", "height"), ("体长", "length"), ("全长", "length"),
    ("长度", "length"), ("体重", "weight"), ("重量", "weight"), ("自重", "weight"), ("净重", "weight"), ("功率", "power"),
    ("输出", "power"), ("时速", "speed"), ("航速", "speed"), ("速度", "speed"), ("射程", "range"), ("宽度", "width"),
    ("厚度", "thick"), ("高", "height"), ("长", "length"), ("重", "weight"), ("宽", "width"), ("厚", "thick"), ("深", "depth"),
]
_ATTR_WORDS = "|".join(re.escape(a) for a, _ in ATTRS)
_ATTR_DIM = dict(ATTRS)
_FILLER = re.compile(r"(?:约|约莫|足有|足足|足|将近|接近|差不多|大概|大约|少说也?有|起码|至少|只有|才|刚|已经|整整|竟然|居然|竟|有|达|达到|是|了|为|在|足有|超过|不到|仅|仅有)$")
_APPROX = re.compile(r"约|大概|大约|将近|接近|差不多|左右|多|余|几|上下|起码|至少|少说|超过|不到")
_AGE_PRE_FILLER = re.compile(r"(?:今年|已经|刚满|已满|年方|年仅|才|刚|满|不过|也就|今年才|今年刚|已|快|快要|都)$")
_AGE_BAD_POST = re.compile(r"^(?:那年|那会|时|的时候|之前|以前|以后|开始|起|左右的孩子|出头|上下|多|半)")
_AGE_BAD_PRE = re.compile(r"(?:比[\u4e00-\u9fff]{0,3}[大小长]|[大小长]了?[他她我你]|差|相差|多活了|前|再过|还有|过了|当年|那年)$")
_DEMO = re.compile(r".*(?:[这那一每][块台具把个头座艘架辆只尊件根条位名])")
_STOP_OBJ = {"他", "她", "它", "我", "你", "这", "那", "对方", "此人", "众人", "身体", "全身", "整个"}

# 境界
REALMS = ("炼气", "练气", "筑基", "金丹", "元婴", "化神", "炼虚", "合体", "大乘", "渡劫", "斗之气", "大斗师", "斗者", "斗师", "斗灵",
          "斗王", "斗皇", "斗宗", "斗尊", "斗圣", "斗帝", "武徒", "武者", "大武师", "武师", "武宗", "武王", "武皇", "武尊",
          "大宗师", "宗师", "先天", "后天", "通脉", "锻体", "淬体", "炼体", "开脉", "聚气", "凝气", "凝脉", "铜皮", "铁骨", "气海")
_REALM_RX = re.compile(rf"({'|'.join(sorted(REALMS, key=len, reverse=True))})(?:境)?(?:第)?({NUM})(层|重|阶|级|星|段|品|转)")
_REALM_RX2 = re.compile(rf"({NUM})(阶|级|品|星)(?:的)?({'|'.join(sorted(REALMS, key=len, reverse=True))})")
_BREAK = re.compile(r"突破|晋升|晋级|踏入|迈入|跨入|进阶|升到|升至|提升到|提升至|冲上|冲破|破境|跌落|跌回|掉到|降到")

# 期限
_REL_DAYS = {"明天": 1, "明日": 1, "后天": 2, "后日": 2, "大后天": 3}
_EVENT = r"([\u4e00-\u9fff]{2,6}?)(?=[，。！？；、”」\s]|就|便|要|会|还|也|之|他|她|你|我|的|了|上|前|里|$)"
_DAYS_RX = [
    re.compile(rf"({NUM})\s*(?:天|日)(?:之|以)?后的?{_EVENT}"),
    re.compile(rf"(大后天|明天|明日|后天|后日)的?{_EVENT}"),
]
_DAYS_RX_REV = [
    re.compile(rf"([\u4e00-\u9fff]{{2,6}})(?:就|便|都)?(?:在|定在|是|安排在|放在|改到|挪到)({NUM}\s*(?:天|日)(?:之|以)?后|大后天|明天|明日|后天|后日)"),
    re.compile(rf"(?:离|距离|距)([\u4e00-\u9fff]{{2,6}}?)(?:只剩|仅剩|还剩|还有|剩下|只有)(?:不到)?({NUM})\s*(?:天|日)"),
]
_TIME_SKIP = re.compile(r"第二天|次日|翌日|隔天|隔日|一夜过去|一夜无话|天亮了|天刚亮|过了一天|过了两天|转眼|一天后|两天后|当晚|入夜|第三天")
_EVENT_STOP = {"时间", "时候", "早上", "上午", "下午", "晚上", "中午", "一早", "再说", "再来", "见面", "开始", "就是", "这个", "那个"}

_SENT_DELIM = "。！？!?\n"


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    a = pos
    while a > 0 and text[a - 1] not in _SENT_DELIM:
        a -= 1
    b = pos
    while b < len(text) and text[b] not in _SENT_DELIM:
        b += 1
    if b < len(text) and text[b] in "。！？!?":
        b += 1
        while b < len(text) and text[b] in "”」\"":
            b += 1
    return a, b


def _quote(text: str, pos: int, max_len: int = 80) -> str:
    a, b = _sentence_bounds(text, pos)
    while a < b and (text[a].isspace() or text[a] in "”」"):
        a += 1
    if b - a > max_len:
        a = max(a, min(b - max_len, pos - max_len // 2))
        b = a + max_len
    return text[a:b].strip()


def _para_index(text: str, pos: int) -> int:
    idx, i = 0, 0
    for m in re.finditer(r"\n+", text):
        if m.start() >= pos:
            break
        if text[i:m.start()].strip():
            idx += 1
        i = m.end()
    return idx


@dataclass
class Mention:
    obj: str
    dim: str
    value: float
    raw: str
    unit: str
    system: str
    pos: int
    approx: bool
    source: str = "chapter"  # chapter / ledger
    label: str = ""          # ledger：来源说明（设定卡/事实账本 key）
    sub: str = ""            # realm：境界名


def _strip_filler(s: str) -> str:
    prev = None
    while prev != s:
        prev = s
        s = _FILLER.sub("", s)
    return s


def _object_from(chunk: str, names: Sequence[str]) -> str | None:
    """属性词之前的那一小段里取对象：优先认人名/实体名，其次取指示词+量词之后的名词。"""
    chunk = chunk.rstrip("的之")
    if not chunk:
        return None
    best = None
    for n in names:
        if n and chunk.endswith(n) and (best is None or len(n) > len(best)):
            best = n
    if best:
        return best
    m = re.search(r"([\u4e00-\u9fffA-Za-z0-9·]{1,8})$", chunk)
    if not m:
        return None
    obj = m.group(1)
    d = _DEMO.match(obj)
    if d:
        obj = obj[d.end():]
    obj = re.sub(r"^(?:看见|看着|发现|只见|望着|盯着|面前的|眼前的|那|这|其)", "", obj).lstrip("的")
    for n in names:  # 名字在中间（“叶承这副身板”）也算这个人
        if n and len(n) >= 2 and n in obj:
            return n
    if len(obj) < 2 or obj in _STOP_OBJ:
        return None
    return obj


def _attr_before(pre: str) -> tuple[str, str] | None:
    """pre（数字之前同一分句的文字，去掉了“约/足有”等垫词）以属性词结尾 → (属性维度, 属性词之前的文字)。"""
    m = re.search(rf"({_ATTR_WORDS})(?:达|约|有|为|是|了)?$", pre)
    if not m:
        return None
    return _ATTR_DIM[m.group(1)], pre[:m.start()]


def _clause_start(text: str, pos: int) -> int:
    a = pos
    while a > 0 and text[a - 1] not in "，,；;：:。！？!?\n“”「」":
        a -= 1
    return a


def extract_mentions(text: str, names: Sequence[str] = (), source: str = "chapter", label: str = "") -> list[Mention]:
    names = sorted({n for n in names if n and len(n) >= 2}, key=len, reverse=True)
    out: list[Mention] = []
    taken: list[tuple[int, int]] = []
    last_obj_in_sent: dict[int, str] = {}

    def remember(pos: int, obj: str) -> None:
        last_obj_in_sent[_sentence_bounds(text, pos)[0]] = obj

    def inherit(pos: int) -> str | None:
        """分句没写对象（“身高一米八，体重七十公斤”）：沿用同一句里前面最近的人名/上一处数值的对象。"""
        a = _sentence_bounds(text, pos)[0]
        seg = text[a:pos]
        best, at = None, -1
        for n in names:
            k = seg.rfind(n)
            if k > at:
                best, at = n, k
        return best or last_obj_in_sent.get(a)

    # 境界（先吃掉，避免“后天三层”被当成期限）
    for rx, order in ((_REALM_RX, "name_first"), (_REALM_RX2, "num_first")):
        for m in rx.finditer(text):
            if order == "name_first":
                realm, num, unit = m.group(1), m.group(2), m.group(3)
            else:
                num, unit, realm = m.group(1), m.group(2), m.group(3)
            v = cn_to_num(num)
            if v is None:
                continue
            taken.append(m.span())
            a = _sentence_bounds(text, m.start())[0]
            pre = text[max(a, m.start() - 30):m.start()]
            obj = None
            for n in names:
                k = pre.rfind(n)
                if k >= 0 and (obj is None or k > pre.rfind(obj)):
                    obj = n
            obj = obj or inherit(m.start())
            if not obj:
                continue
            remember(m.start(), obj)
            out.append(Mention(obj, f"realm:{realm}", v, m.group(0), unit, "realm", m.start(), False, source, label, realm))

    # 重量 / 长度 / 功率
    for m in _MEASURE_RX.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        num, unit, tail = m.group(1), m.group(2), m.group(3)
        v = cn_to_num(num)
        if v is None:
            continue
        dim_u, factor, system = UNITS[unit]
        if unit == "米" and tail:  # 一米八 = 1.8 米
            t = cn_to_num(tail)
            if t is not None and t < 10:
                v = v + t / 10
        base = v * factor
        cs = _clause_start(text, m.start())
        pre_raw = text[cs:m.start()]
        pre = _strip_filler(pre_raw)
        post = text[m.end():m.end() + 6]
        dim = None
        obj = None
        ab = _attr_before(pre)
        if ab:
            attr_dim, before = ab
            dim = attr_dim
            obj = _object_from(_strip_filler(before), names)
        else:
            pm = re.match(rf"^(?:多)?(?:的)?({_ATTR_WORDS})", post)
            if pm:
                dim = _ATTR_DIM[pm.group(1)]
                obj = _object_from(_strip_filler(pre), names)
                if not obj:  # “一米八的个头的叶承”这种很少见；“十八米高的天罡号”
                    nm = re.match(rf"^(?:多)?(?:的)?(?:{_ATTR_WORDS})的([\u4e00-\u9fff]{{2,6}})", post + text[m.end() + 6:m.end() + 12])
                    if nm:
                        obj = _object_from(nm.group(1), names) or nm.group(1)
        if dim is None:
            continue
        # 属性维度与单位维度要兼容（“高三百斤”不比）
        if dim in ("height", "length", "width", "thick", "depth", "range") and dim_u != "length":
            continue
        if dim == "weight" and dim_u != "weight":
            continue
        if dim == "power" and dim_u != "power":
            continue
        if dim == "speed":
            if unit not in ("公里", "千米"):
                continue
        obj = obj or inherit(m.start())
        if not obj:
            continue
        remember(m.start(), obj)
        approx = bool(_APPROX.search(pre_raw[-6:] + post[:3]))
        out.append(Mention(obj, dim, base, m.group(0), unit, system, m.start(), approx, source, label))

    # 年龄
    for m in _AGE_RX.finditer(text):
        v = cn_to_num(m.group(1))
        if v is None or v <= 0 or v > 2000:
            continue
        cs = _clause_start(text, m.start())
        pre_raw = text[cs:m.start()]
        post = text[m.end():m.end() + 8]
        if _AGE_BAD_POST.match(post) or _AGE_BAD_PRE.search(pre_raw):
            continue
        pre = pre_raw
        prev = None
        while prev != pre:
            prev = pre
            pre = _AGE_PRE_FILLER.sub("", _strip_filler(pre))
        pre = re.sub(r"(?:年龄|年纪|岁数)(?:是|为|有)?$", "", pre)
        obj = None
        for n in names:
            if pre.endswith(n):
                obj = n
                break
        if obj is None:
            pm = re.match(r"^的([\u4e00-\u9fff]{2,4})", post)
            if pm:
                obj = next((n for n in names if pm.group(1).startswith(n)), None)
        if obj is None and source == "ledger":
            obj = next((n for n in names if pre.startswith(n)), None)
        if not obj:
            continue
        approx = bool(re.match(r"^(?:多|出头|左右|上下)", post)) or "几" in m.group(1)
        out.append(Mention(obj, "age", v, m.group(0), "岁", "age", m.start(), approx, source, label))

    # 期限（只在正文里比）
    if source == "chapter":
        for rx in _DAYS_RX:
            for m in rx.finditer(text):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                d = _REL_DAYS.get(m.group(1))
                if d is None:
                    v = cn_to_num(m.group(1))
                    if v is None:
                        continue
                    d = int(v)
                ev = m.group(2)
                if ev in _EVENT_STOP or len(ev) < 2:
                    continue
                out.append(Mention(ev, "days", float(d), m.group(0), "天", "days", m.start(), False, source, label))
        for rx in _DAYS_RX_REV:
            for m in rx.finditer(text):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                ev, when = m.group(1), m.group(2)
                ev = re.sub(r"^(?:这场|那场|这次|那次|本次|今年的|这一届|下一场)", "", ev)
                if ev in _EVENT_STOP or len(ev) < 2:
                    continue
                d = _REL_DAYS.get(when)
                if d is None:
                    nm = re.match(rf"({NUM})", when)
                    v = cn_to_num(nm.group(1)) if nm else None
                    if v is None:
                        continue
                    d = int(v)
                out.append(Mention(ev, "days", float(d), m.group(0), "天", "days", m.start(), False, source, label))
    out.sort(key=lambda x: x.pos)
    return out


# ------------------------------------------------------------------ 比较

DIM_LABEL = {"weight": "重量", "height": "身高/高度", "length": "长度", "width": "宽度", "thick": "厚度", "depth": "深度",
             "range": "射程", "power": "功率", "speed": "时速", "age": "年龄", "days": "时间"}


def _same_obj(a: str, b: str) -> bool:
    return a == b or (len(a) >= 2 and len(b) >= 2 and (a in b or b in a))


def _conflict(a: Mention, b: Mention) -> bool:
    if a.value == b.value:
        return False
    if a.dim == "age":
        return abs(a.value - b.value) >= (2 if (a.approx or b.approx) else 1)
    if a.dim == "days" or a.dim.startswith("realm:"):
        return True
    tol = 0.15 if (a.approx or b.approx) else 0.04
    hi = max(abs(a.value), abs(b.value)) or 1.0
    return abs(a.value - b.value) / hi > tol


def _fmt(m: Mention) -> str:
    return f"「{m.raw}」" + (f"（{m.label}）" if m.source == "ledger" and m.label else "")


def numeric_consistency(text: str, names: Sequence[str] = (), ledger: Sequence[dict[str, Any]] | None = None,
                        max_issues: int = 8) -> list[dict[str, Any]]:
    """返回审稿 issue 列表：{severity, dimension:"continuity", quote, comment, position{offset, paragraph}, related, source, object, kind}。"""
    if not text:
        return []
    led_names = [str(e.get("entity") or "") for e in (ledger or [])]
    all_names = [n for n in dict.fromkeys([*names, *led_names]) if n]
    chapter = extract_mentions(text, all_names)
    led: list[Mention] = []
    for e in ledger or []:
        ent, key, val = str(e.get("entity") or ""), str(e.get("key") or ""), str(e.get("value") or "")
        if not ent or not val:
            continue
        if re.fullmatch(r"\s*\d+\s*", val) and re.search(r"年龄|年纪|岁数|age", key, re.I):
            val = val.strip() + "岁"
        key2 = key if re.search(_ATTR_WORDS + r"|年龄|年纪|岁数|境界|修为|实力", key) else ""
        led += extract_mentions(f"{ent}{key2}{val}", all_names, "ledger", str(e.get("source") or key))
    issues: list[dict[str, Any]] = []
    reported: set[tuple[str, str, float]] = set()

    def add(m: Mention, base: Mention, comment: str, severity: str = "mid") -> None:
        key = (m.obj, m.dim, round(m.value, 3))
        if key in reported:
            return
        reported.add(key)
        issue: dict[str, Any] = {
            "severity": severity, "dimension": "continuity", "quote": _quote(text, m.pos), "comment": comment,
            "position": {"offset": m.pos, "paragraph": _para_index(text, m.pos), "match": m.raw},
            "source": "lint:numeric", "object": m.obj, "kind": m.dim.split(":")[0],
        }
        if base.source == "chapter":
            issue["related"] = {"quote": _quote(text, base.pos), "offset": base.pos, "paragraph": _para_index(text, base.pos)}
        else:
            issue["related"] = {"source": "ledger", "label": base.label, "value": base.raw}
        issues.append(issue)

    groups: dict[tuple[str, str], list[Mention]] = {}
    for m in chapter:
        k = next((g for g in groups if g[1] == m.dim and _same_obj(g[0], m.obj)), (m.obj, m.dim))
        groups.setdefault(k, []).append(m)
    for (obj, dim), ms in groups.items():
        label = DIM_LABEL.get(dim, "境界" if dim.startswith("realm:") else dim)
        base_led = next((x for x in led if x.dim == dim and _same_obj(x.obj, obj)), None)
        realm = dim.startswith("realm:")
        if base_led is not None and not (realm and _BREAK.search(text)):
            for m in ms:
                if _conflict(m, base_led):
                    add(m, base_led, f"{obj}的{label}：本章写{_fmt(m)}，设定/账本记的是{_fmt(base_led)}。"
                                    f"若是本章改变了，请在变更声明里更新；否则统一成一个数")
        base = ms[0]
        for m in ms[1:]:
            between = text[base.pos:m.pos]
            if dim == "days" and _TIME_SKIP.search(between):
                base = m
                continue
            if realm and _BREAK.search(between):
                base = m
                continue
            if _conflict(m, base):
                add(m, base, f"{obj}的{label}前后不一致：前面写{_fmt(base)}，这里写{_fmt(m)}"
                             + ("；若中间已经过了一天，补一句时间推进" if dim == "days" else "，统一成一个数"))
        # 同一对象同一项混用市制与公制（数值对得上也提示）
        systems = {m.system for m in ms if m.system in ("metric", "market")}
        if len(systems) > 1:
            mk = next(m for m in ms if m.system != ms[0].system)
            if (obj, dim, round(mk.value, 3)) not in reported:
                add(mk, ms[0], f"{obj}的{label}单位混用：{_fmt(ms[0])}与{_fmt(mk)}（市制/公制），同一对象全书用一种单位")
        if len(issues) >= max_issues:
            break
    return issues[:max_issues]
