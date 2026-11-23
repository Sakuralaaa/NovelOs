"""大纲：总纲 → 卷 → 弧 → 章细纲，滚动展开。chapter 级节点的 order 即全书章号。"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlmodel import Session, func, select

from app.services.research import research_notes
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Book, OutlineNode, utcnow
from app.services import common
from app.services.common import Conflict, NotFound
from app.skills.loader import render, system_prompt

OUTCOMES = ("yes", "no", "yes-but", "no-and")
CHAPTERS_PER_ARC = 5

# ---- 节奏字段（均为可选；旧细纲没有这些键时按“未标注”处理，不影响写作）----
# 爽点执行模式（思路参考 lingfengQAQ/webnovel-writer cool-points-guide，GPL-3.0，仅借思路，文字自写）
PAYOFF_TYPES = ("打脸", "扮猪吃虎", "越级反杀", "打脸权威", "反派翻车", "甜蜜超预期", "真相揭示", "收获升级", "危机化解", "关系突破")
# 爽点强度：small 小爽点 / combo 组合爽点（两种模式叠加）/ milestone 里程碑（改变主角地位）
PAYOFF_LEVELS = ("small", "combo", "milestone")
# 章末钩子类型（危机突降/悬念反转/挑衅叫板/倒计时 + 信息缺口/选择悬置/后果预示 + 决定/发现/误判/代价）
HOOK_TYPES = ("危机突降", "悬念反转", "挑衅叫板", "倒计时", "信息缺口", "选择悬置", "后果预示", "决定", "发现", "误判", "代价")
# 叙事线：quest 主线 / fire 感情与人物关系线 / constellation 世界观与势力扩展（Strand Weave 思路，XuanRanL/webnovelwriter，GPL-3.0，仅借思路）
STRANDS = ("quest", "fire", "constellation")
EMOTIONS = ("up", "down", "flat")  # 本章读者情绪走向：扬 / 压 / 平
FORESHADOW_TIERS = ("short", "mid", "long")  # 伏笔层级：10 章内 / 30 章内 / 50 章以上回收
# v0.18 阻力类型：同一种阻力连着写，读者会觉得在原地打转；文书手续类阻力最容易写成“打工人受气”
CONFLICT_TYPES = ("武力挑衅", "擂台比试", "猎杀探险", "阴谋暗算", "利益争夺", "规则刁难", "身份质疑", "情感关系", "外敌危机")
PAPER_TYPES = ("规则刁难", "身份质疑")
PAPER_RX = re.compile(r"报名表|签字|复核|审查|名额|档案|除名|手续|盖章|教务|举报|担保|批文|名册|退学|资格|评级复查|复查单|户籍|调房|申请")
MAX_SAME_CONFLICT_RUN = 2    # 同一种阻力连续超过 2 章 → 原地打转
PAPER_WINDOW, PAPER_MAX = 5, 1  # 任意连续 5 章里，文书手续类阻力最多 1 章
PROMISE_FIRST_BY = 3         # 简介里第一个卖点场面最晚第 3 章兑现
PROMISE_CORE_BY = 10         # 书名/简介的核心卖点最晚第 10 章第一次完整兑现

# 节奏红线（经验值，未校准）
MAX_SAME_PAYOFF_RUN = 2      # 同一爽点模式连续超过 2 章 → 审美疲劳
MAX_SAME_HOOK_RUN = 2        # 同一钩子类型连续超过 2 章 → 套路感
MAX_YES_RUN = 2              # 章结果连续 yes 超过 2 章 → 节奏塌陷
MAX_SAME_EMOTION_RUN = 2     # 情绪同方向连续超过 2 章（novel-ops：连续 3 章同方向强制调整）
MAX_QUEST_RUN = 5            # 主线连续不超过 5 章
MAX_FIRE_GAP = 10            # 感情/关系线断档不超过 10 章
MAX_CONSTELLATION_GAP = 15   # 世界观扩展断档不超过 15 章
COMBO_WINDOW = 5             # 每 5 章至少 1 个组合爽点
MILESTONE_WINDOW = 15        # 每 15 章至少 1 个里程碑爽点
FORESHADOW_WARN_AGE = 20     # 伏笔超过 20 章无推进标黄（novel-ops）
FORESHADOW_ALERT_AGE = 40    # 超过 40 章标红


def _pick(v: Any, allowed: tuple[str, ...]) -> str:
    v = str(v or "").strip()
    if v in allowed:
        return v
    for a in allowed:  # 容忍“打脸（当众）”“quest主线”这类带注释的写法
        if a and a in v:
            return a
    return ""


def _strands(v: Any) -> list[str]:
    items = v if isinstance(v, list) else [v] if v else []
    out: list[str] = []
    for it in items:
        k = _pick(str(it).lower(), STRANDS)
        if k and k not in out:
            out.append(k)
    return out


CHAPTER_SCHEMA = (
    '{"chapters":[{"title":"","goal":"本章戏剧问题","want":"主角本章主动想要什么（去争、去拿、去查、去赢）",'
    '"conflict":"阻力：谁或什么在拦","turn":"转折：局面在哪一刻掉头","result":"结果：主角得到/失去什么、局面变成什么样",'
    '"outcome":"yes|no|yes-but|no-and","payoff":"","payoff_mechanism":"爽点机制一句话：谁输、怎么输、谁看见、主角得到什么",'
    '"payoff_type":"打脸|扮猪吃虎|越级反杀|打脸权威|反派翻车|甜蜜超预期|真相揭示|收获升级|危机化解|关系突破",'
    '"payoff_level":"small|combo|milestone","strand":["quest|fire|constellation"],"emotion":"up|down|flat",'
    '"conflict_type":"武力挑衅|擂台比试|猎杀探险|阴谋暗算|利益争夺|规则刁难|身份质疑|情感关系|外敌危机",'
    '"expectation":"本章挂起或兑现的读者期待","info_gap":"读者知道而角色不知道的事（可空）","time":"本章故事内时间",'
    '"opening_hook":"第1–3章必填：正文前三行就出现的冲突或异常（写成画面）","cheat_beat":"每章必填：金手指本章怎么用、兑现了什么（可写“本章不用”，但每 3 章至少一次可见兑现且有收获）",'
    '"core_scene":"核心场景（地点与画面氛围）","underlying_game":"底层博弈（谁算计谁、信息差在哪）","chapter_reward":"本章收益（具体可比较的收获）",'
    '"stage_qi":"起（入局冲突，150–250字）","stage_cheng":"承（加压博弈，200–300字）","stage_zhuan":"转（反转爆点，200–300字）","stage_he":"合（收益与章末卡点，150–250字）",'
    '"characters":[],"location":"","foreshadow":[{"action":"plant|advance|resolve","id":null,"desc":"","tier":"short|mid|long"}],'
    '"hook_end":"章末最后一拍：停在哪个事件进行中或谁的哪句话上（写要发生什么，不写台词原句）","hook_type":"危机突降|悬念反转|挑衅叫板|倒计时|信息缺口|选择悬置|后果预示|决定|发现|误判|代价","must_avoid":[]}]}'
)


def _maybe_json(v: Any) -> Any:
    """编辑器把列表/对象存成了 JSON 字符串时还原（旧版前端保存细纲会这样，导致伏笔和出场人物丢失）。"""
    if isinstance(v, str) and v.strip()[:1] in ("[", "{"):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def normalize_beats(raw: dict[str, Any], number: int, chapter_words: int) -> dict[str, Any]:
    raw = {k: _maybe_json(v) if k in ("foreshadow", "characters", "must_avoid", "strand", "scenes") else v for k, v in (raw or {}).items()}
    fs = []
    for f in raw.get("foreshadow") or []:
        if isinstance(f, dict) and f.get("action") in ("plant", "advance", "resolve"):
            fid = f.get("id")
            item: dict[str, Any] = {"action": f["action"], "id": fid if isinstance(fid, int) else None, "desc": str(f.get("desc", ""))}
            tier = _pick(f.get("tier"), FORESHADOW_TIERS)
            if f["action"] == "plant" and tier:
                item["tier"] = tier
            fs.append(item)
    outcome = raw.get("outcome") if raw.get("outcome") in OUTCOMES else "yes-but"
    chars = [str(c) for c in (raw.get("characters") or []) if c]
    out: dict[str, Any] = {
        "number": number,
        "title": str(raw.get("title") or f"第{number}章"),
        "goal": str(raw.get("goal", "")),
        "conflict": str(raw.get("conflict", "")),
        "outcome": outcome,
        "payoff": str(raw.get("payoff", "")),
        "characters": chars,
        "location": str(raw.get("location", "")),
        "foreshadow": fs,
        "hook_end": str(raw.get("hook_end", "")),
        "words": int(raw.get("words") or chapter_words),
    }
    # 可选的节奏字段：只在模型给了合法值时写入，保持旧数据与前端键值编辑兼容
    optional = {
        "payoff_type": _pick(raw.get("payoff_type"), PAYOFF_TYPES),
        "payoff_level": _pick(str(raw.get("payoff_level") or "").lower(), PAYOFF_LEVELS),
        "hook_type": _pick(raw.get("hook_type"), HOOK_TYPES),
        "emotion": _pick(str(raw.get("emotion") or "").lower(), EMOTIONS),
        "conflict_type": _pick(raw.get("conflict_type"), CONFLICT_TYPES),
    }
    for k, v in optional.items():
        if v:
            out[k] = v
    st = _strands(raw.get("strand") or raw.get("strands"))
    if st:
        out["strand"] = st
    for k in ("expectation", "info_gap", "time", "opening_hook", "cheat_beat", "want", "turn", "result", "payoff_mechanism"):
        if raw.get(k):
            out[k] = str(raw[k])[:200]
    # v0.21 重纲轻写：起/承/转/合千字详纲字段（支持中英文别名）
    heavy_aliases = (
        ("stage_qi", ("起", "qi")),
        ("stage_cheng", ("承", "cheng")),
        ("stage_zhuan", ("转", "zhuan")),
        ("stage_he", ("合", "he")),
    )
    for k, aliases in heavy_aliases:
        v = raw.get(k)
        if not v:
            for a in aliases:
                if raw.get(a):
                    v = raw[a]
                    break
        if v:
            out[k] = str(v).strip()[:600]
    meta_aliases = (
        ("core_scene", ("核心场景",)),
        ("underlying_game", ("底层博弈",)),
        ("chapter_reward", ("本章收益",)),
        ("phase_check", ("阶段检查",)),
    )
    for k, aliases in meta_aliases:
        v = raw.get(k)
        if not v:
            for a in aliases:
                if raw.get(a):
                    v = raw[a]
                    break
        if v:
            out[k] = str(v).strip()[:300]
    avoid = raw.get("must_avoid")
    if isinstance(avoid, list) and avoid:
        out["must_avoid"] = [str(x)[:80] for x in avoid if x][:5]
    elif isinstance(avoid, str) and avoid.strip():
        out["must_avoid"] = [avoid.strip()[:80]]
    return out


CHEAT_IDLE = "本章不用"
CHEAT_GAP = 3           # 金手指：每 3 章至少一次可见兑现
MECHANISM_WINDOW = 5    # 爽点机制查重：和最近 5 章比
MECHANISM_SIM = 0.5     # 二字词重合度达到这个就算同一种机制
DEFENSIVE_RX = re.compile(r"(躲|逃|藏|撑过|熬过|保住|守住|不被|避开|避免|活下来|活过|自保|苟)")
MAX_DEFENSIVE_RUN = 2   # 主角目标连续是防守题的章数上限


def cheat_idle(text: Any) -> bool:
    t = str(text or "").strip()
    return not t or t.startswith(("本章不用", "不用", "无")) or t in ("本章不出手", "-")


def ensure_opening_beats(beats: dict[str, Any], number: int, cheat: Any | None = None, tagline: str = "",
                         recent: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """读者账本兜底（v0.6 开篇硬约束，v0.17 扩成每章）：
    - 第 1–3 章必须有 opening_hook；
    - 每章都有 want（主角主动想要什么）与 cheat_beat（金手指本章怎么用；可以“本章不用”，
      但最近 CHEAT_GAP-1 章都没用时本章必须可见兑现）；
    - 爽点机制和最近 MECHANISM_WINDOW 章重复时，写进 must_avoid 让写手换一种落法。
    recent：本章之前的章细纲（chapter_beats_list 的元素），可省略。"""
    b = dict(beats or {})
    recent = [x for x in (recent or []) if int(x.get("number") or 0) < number]
    if number <= 3 and not str(b.get("opening_hook") or "").strip():
        core = b.get("conflict") or b.get("goal") or ""
        b["opening_hook"] = f"开篇三行内让冲突落到主角身上：{core}"[:200]
    if not str(b.get("want") or "").strip() and str(b.get("goal") or "").strip():
        b["want"] = f"主角主动去争取：{b['goal']}"[:200]
    how = ""
    if cheat is not None:
        d = getattr(cheat, "data", None) or {}
        how = str(d.get("input") or getattr(cheat, "summary", "") or "")
    label = f"「{cheat.name}」" if cheat is not None else "核心卖点"
    if number == 1 and cheat_idle(b.get("cheat_beat")):
        if cheat is not None:
            b["cheat_beat"] = (f"让{label}露一次可感知的苗头：{how}。写成主角能感到的具体反馈（数字、提示、身体感受或一次小收益），"
                               "一两句交代清楚")[:200]
        elif tagline:
            b["cheat_beat"] = f"让核心卖点露一次可感知的苗头：{tagline}"[:200]
    elif number > 1 and (cheat is not None or tagline):
        last = sorted(recent, key=lambda x: int(x.get("number") or 0))[-(CHEAT_GAP - 1):]
        idle_run = len(last) >= CHEAT_GAP - 1 and all(cheat_idle(x.get("cheat_beat")) for x in last)
        if idle_run and cheat_idle(b.get("cheat_beat")):
            b["cheat_beat"] = (f"{label}本章可见地兑现一次：{how or tagline}。写清怎么触发、给了什么、主角拿它干成了什么，"
                               "收获写成能比较的结果")[:200]
        elif not str(b.get("cheat_beat") or "").strip():
            b["cheat_beat"] = CHEAT_IDLE
    if b.get("payoff_mechanism"):
        dup = mechanism_dupes([*recent[-MECHANISM_WINDOW:], {**b, "number": number}], MECHANISM_WINDOW)
        hit = next((d for d in dup if d[0] == number), None)
        if hit is not None:
            line = f"别再用和第{hit[1]}章一样的爽点机制（{hit[2][:40]}），同一个结果换一种输法、换一个见证人"
            avoid = [str(x) for x in (b.get("must_avoid") or []) if x]
            if line not in avoid:
                b["must_avoid"] = [*avoid, line][-5:]
    return b


def _grams(text: str) -> set[str]:
    out: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", str(text or "")):
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


def mechanism_similarity(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


def mechanism_dupes(chapters: list[dict[str, Any]], window: int = MECHANISM_WINDOW,
                    threshold: float = MECHANISM_SIM) -> list[tuple[int, int, str]]:
    """爽点机制查重：每章和它之前 window 章比，二字词重合度 ≥ threshold 视为同一种机制。
    返回 [(章号, 撞车的更早章号, 本章机制)]。"""
    chs = sorted([c for c in chapters if isinstance(c, dict) and c.get("number") and c.get("payoff_mechanism")],
                 key=lambda c: int(c["number"]))
    out: list[tuple[int, int, str]] = []
    for i, c in enumerate(chs):
        n = int(c["number"])
        for p in reversed(chs[max(0, i - window):i]):
            if n - int(p["number"]) > window:
                continue
            if mechanism_similarity(str(c["payoff_mechanism"]), str(p["payoff_mechanism"])) >= threshold:
                out.append((n, int(p["number"]), str(c["payoff_mechanism"])))
                break
    return out


# ------------------------------------------------------------------ 节奏审计（纯代码）

def _runs(values: list[tuple[int, str]]) -> list[tuple[str, int, int]]:
    """把（章号, 值）序列压成连续段：(值, 起始章, 结束章)。空值打断连续。"""
    out: list[tuple[str, int, int]] = []
    for n, v in values:
        if out and v and out[-1][0] == v and out[-1][2] == n - 1:
            out[-1] = (v, out[-1][1], n)
        elif v:
            out.append((v, n, n))
    return out


def pacing_audit(chapters: list[dict[str, Any]], open_foreshadows: list[Any] | None = None,
                 current: int | None = None) -> list[str]:
    """对一段按章号排序的章细纲做节奏体检，返回问题清单（中文，可直接喂给规划提示词）。

    只检查模型标注过的字段；未标注的章节不参与对应检查。阈值为经验值，未校准。
    """
    chs = sorted([c for c in chapters if isinstance(c, dict) and c.get("number")], key=lambda c: int(c["number"]))
    issues: list[str] = []
    if not chs:
        return issues
    seq = lambda key: [(int(c["number"]), str(c.get(key) or "")) for c in chs]  # noqa: E731
    for v, a, b in _runs(seq("payoff_type")):
        if b - a + 1 > MAX_SAME_PAYOFF_RUN:
            issues.append(f"第{a}–{b}章连续 {b - a + 1} 章都是「{v}」式爽点，读者会疲劳，换一种模式或穿插感情线/世界观章")
    for v, a, b in _runs(seq("hook_type")):
        if b - a + 1 > MAX_SAME_HOOK_RUN:
            issues.append(f"第{a}–{b}章连续 {b - a + 1} 章用「{v}」式章末钩子，换一种钩子类型")
    ctypes = [(int(c["number"]), conflict_kind(c)) for c in chs]
    for v, a, b in _runs(ctypes):
        if b - a + 1 > MAX_SAME_CONFLICT_RUN:
            issues.append(f"第{a}–{b}章连续 {b - a + 1} 章的阻力都是「{v}」，读者会觉得在原地打转：换一种阻力（真刀真枪的对手、比试、猎杀、抢东西、暗算）")
    paper = [n for n, v in ctypes if v in PAPER_TYPES]
    for i, n in enumerate(paper):
        inside = [m for m in paper[i:] if m - n < PAPER_WINDOW]
        if len(inside) > PAPER_MAX:
            issues.append(f"第{inside[0]}–{inside[-1]}章有 {len(inside)} 章的阻力是报名、签字、复核、审查这类手续刁难，读起来像在办事处受气："
                          f"连续 {PAPER_WINDOW} 章里最多留 1 章，其余换成对手当面出手、比试或抢资源，手续问题让主角用实力一次掀掉")
            break
    for v, a, b in _runs([(n, o if o == "yes" else "") for n, o in seq("outcome")]):
        if b - a + 1 > MAX_YES_RUN:
            issues.append(f"第{a}–{b}章连续 {b - a + 1} 章结果都是 yes，主角太顺，至少一章改成 yes-but 或 no-and")
    for v, a, b in _runs(seq("emotion")):
        if v in ("up", "down") and b - a + 1 > MAX_SAME_EMOTION_RUN:
            label = "扬" if v == "up" else "压"
            issues.append(f"第{a}–{b}章情绪连续 {b - a + 1} 章都在「{label}」，需要一章反向调节")
    tagged = [c for c in chs if c.get("strand")]
    if len(tagged) >= 3:
        quest_only = [(int(c["number"]), "q" if c.get("strand") == ["quest"] else "") for c in tagged]
        for _, a, b in _runs(quest_only):
            if b - a + 1 > MAX_QUEST_RUN:
                issues.append(f"第{a}–{b}章连续 {b - a + 1} 章只走主线，穿插一章感情/人物关系或世界观扩展")
        last = int(chs[-1]["number"])
        for strand, gap, label in (("fire", MAX_FIRE_GAP, "感情/人物关系线"), ("constellation", MAX_CONSTELLATION_GAP, "世界观/势力扩展")):
            hits = [int(c["number"]) for c in tagged if strand in (c.get("strand") or [])]
            first = int(tagged[0]["number"])
            prev = hits[-1] if hits else first - 1
            if last - prev > gap:
                issues.append(f"{label}已经 {last - prev} 章没有推进（上限 {gap} 章），下一弧安排一次")
    for n, m, mech in mechanism_dupes(chs):
        issues.append(f"第{n}章的爽点机制和第{m}章重复（{mech[:30]}），换一种：换输家、换输法、换见证人或换收获")
    wants = [(int(c["number"]), "d" if c.get("want") and DEFENSIVE_RX.search(str(c["want"])) else "") for c in chs]
    for _, a, b in _runs(wants):
        if b - a + 1 > MAX_DEFENSIVE_RUN:
            issues.append(f"第{a}–{b}章主角的目标都是躲、守、撑，读者会憋屈：至少一章改成主角主动去争、去拿、去赢")
    tagged_cheat = [c for c in chs if "cheat_beat" in c]
    if len(tagged_cheat) >= CHEAT_GAP:
        for _, a, b in _runs([(int(c["number"]), "i" if cheat_idle(c.get("cheat_beat")) else "") for c in tagged_cheat]):
            if b - a + 1 >= CHEAT_GAP:
                issues.append(f"第{a}–{b}章金手指都没出手：每 {CHEAT_GAP} 章至少安排一次可见兑现，并带来具体收获")
    levels = [(int(c["number"]), str(c.get("payoff_level") or "")) for c in chs if c.get("payoff_level")]
    if len(levels) >= COMBO_WINDOW:
        nums = [n for n, _ in levels]
        for i in range(0, len(levels) - COMBO_WINDOW + 1):
            window = levels[i : i + COMBO_WINDOW]
            if not any(lv in ("combo", "milestone") for _, lv in window):
                issues.append(f"第{window[0][0]}–{window[-1][0]}章没有组合爽点（每 {COMBO_WINDOW} 章建议至少 1 个）")
                break
        if nums[-1] - nums[0] + 1 >= MILESTONE_WINDOW and not any(lv == "milestone" for _, lv in levels[-MILESTONE_WINDOW:]):
            issues.append(f"最近 {MILESTONE_WINDOW} 章没有里程碑爽点（改变主角地位的阶段胜利），本弧安排一个")
    if open_foreshadows and current:
        for f in open_foreshadows:
            age = current - int(getattr(f, "last_ch", 0) or getattr(f, "planted_ch", 0) or 0)
            if age > FORESHADOW_ALERT_AGE:
                issues.append(f"伏笔 #{getattr(f, 'id', '?')}「{getattr(f, 'desc', '')}」已 {age} 章没有推进（红线 {FORESHADOW_ALERT_AGE}），尽快回收或推进")
            elif age > FORESHADOW_WARN_AGE:
                issues.append(f"伏笔 #{getattr(f, 'id', '?')}「{getattr(f, 'desc', '')}」已 {age} 章没有推进，给一条新线索让读者知道它还活着")
    return issues


def draft_audit(data: dict[str, Any]) -> list[str]:
    """v0.18：大纲 JSON 写库前的开篇体检——阻力类型、手续刁难占比，以及卖点兑现表是否排进了章细纲。"""
    chs: list[dict[str, Any]] = []
    for a in data.get("arcs") or []:
        for c in (a.get("chapters") or []) if isinstance(a, dict) else []:
            if isinstance(c, dict):
                chs.append({**c, "number": len(chs) + 1})
    if not chs:
        return []
    issues = [x for x in pacing_audit(chs) if "阻力" in x or "手续" in x]
    promises = normalize_promises((data.get("book") or {}).get("promises"))
    if not promises:
        issues.append(f"book.promises 没写：把简介和书名向读者承诺的卖点场面列出来，第一个最晚第 {PROMISE_FIRST_BY} 章兑现，核心卖点最晚第 {PROMISE_CORE_BY} 章第一次完整兑现，并排进对应章的 payoff")
    return issues


def conflict_kind(beats: dict[str, Any]) -> str:
    """章细纲的阻力类型：模型标了就用标注；没标但阻力写的是报名、签字、复核这类手续，按「规则刁难」算。"""
    v = str(beats.get("conflict_type") or "")
    if v:
        return v
    return "规则刁难" if PAPER_RX.search(str(beats.get("conflict") or "")) else ""


def normalize_promises(raw: Any, max_chapter: int = 0) -> list[dict[str, Any]]:
    """v0.18 卖点兑现表：[{what, by}]。by 是最晚兑现章号；第一个最晚第 3 章，其余最晚第 10 章（核心卖点）或模型给的章号。"""
    out: list[dict[str, Any]] = []
    for i, p in enumerate(raw if isinstance(raw, list) else []):
        if isinstance(p, str):
            p = {"what": p}
        if not isinstance(p, dict) or not str(p.get("what") or "").strip():
            continue
        try:
            by = int(p.get("by") or 0)
        except (TypeError, ValueError):
            by = 0
        cap = PROMISE_FIRST_BY if i == 0 else PROMISE_CORE_BY
        by = min(by, cap) if by > 0 else cap
        out.append({"what": str(p["what"]).strip()[:120], "by": max(1, by)})
    return out[:6]


def book_promises(s: Session, book_id: int) -> list[dict[str, Any]]:
    root = s.exec(select(OutlineNode).where(OutlineNode.book_id == book_id, OutlineNode.level == "book")).first()
    return list(((root.beats if root else None) or {}).get("promises") or [])


def promises_text(promises: list[dict[str, Any]], number: int) -> str:
    """给规划/审稿看的卖点兑现表，标出到第 number 章为止已经到期的。"""
    lines = []
    for p in promises:
        by = int(p.get("by") or 0)
        tag = "已到期，前文或本章必须已经兑现" if by and by <= number else f"最晚第{by}章兑现"
        lines.append(f"- {p.get('what')}（{tag}）")
    return "\n".join(lines)


def reader_ledger(s: Session, book_id: int, number: int) -> str:
    """v0.18 给读者审稿看的“前几章读到了什么”：卖点兑现表 + 最近几章的阻力与爽点。"""
    parts = []
    pt = promises_text(book_promises(s, book_id), number)
    if pt:
        parts.append("这本书简介向读者承诺的卖点：\n" + pt)
    rows = [b for b in chapter_beats_list(s, book_id) if 0 < int(b.get("number") or 0) < number][-5:]
    recent = [f"第{b['number']}章：阻力「{conflict_kind(b) or str(b.get('conflict') or '')[:30]}」，爽点「{str(b.get('payoff') or '')[:40]}」" for b in rows]
    if recent:
        parts.append("前几章（按章纲）：\n" + "\n".join(recent))
    return "\n\n".join(parts)


def foreshadow_age_label(f: Any, current: int) -> str:
    age = current - int(getattr(f, "last_ch", 0) or getattr(f, "planted_ch", 0) or 0)
    if age > FORESHADOW_ALERT_AGE:
        return f"已 {age} 章未推进，超期红线"
    if age > FORESHADOW_WARN_AGE:
        return f"已 {age} 章未推进，偏久"
    return f"{age} 章前推进过" if age > 0 else "本章前刚推进"


def chapter_beats_list(s: Session, book_id: int) -> list[dict[str, Any]]:
    nodes = s.exec(select(OutlineNode).where(OutlineNode.book_id == book_id, OutlineNode.level == "chapter")
                   .order_by(OutlineNode.order)).all()
    return [{**(n.beats or {}), "number": n.order} for n in nodes]


def rhythm_ledger(beats_list: list[dict[str, Any]], before: int, n: int = 8) -> str:
    """最近 n 章（章号 < before）的节奏标注，供规划/写作时避免重复。"""
    rows = [b for b in beats_list if int(b.get("number") or 0) < before][-n:]
    lines = []
    for b in rows:
        bits = [x for x in (
            b.get("payoff_type") and f"爽点 {b['payoff_type']}" + (f"/{b['payoff_level']}" if b.get("payoff_level") else ""),
            b.get("hook_type") and f"钩子 {b['hook_type']}",
            conflict_kind(b) and f"阻力 {conflict_kind(b)}",
            b.get("outcome") and f"结果 {b['outcome']}",
            b.get("strand") and f"线 {'+'.join(b['strand'])}",
            b.get("emotion") and f"情绪 {b['emotion']}",
            b.get("payoff_mechanism") and f"机制 {str(b['payoff_mechanism'])[:40]}",
        ) if x]
        if bits:
            lines.append(f"第{b['number']}章：" + "，".join(bits))
    return "\n".join(lines)


def _planned_text(s: Session, book_id: int) -> str:
    """作者 / AI 规划好、还没写进正文的伏笔，展开细纲时按计划章号安排“埋下”。"""
    from app.models.tables import Foreshadow

    rows = s.exec(select(Foreshadow).where(Foreshadow.book_id == book_id, Foreshadow.status == "planned")).all()
    if not rows:
        return ""
    return "\n计划中的伏笔（还没写进正文，到计划章号时在细纲里安排 plant，desc 原样照抄）：\n" + "\n".join(
        f"- {f.desc}" + (f"（计划第{f.plan_plant_ch}章埋" if f.plan_plant_ch else "（埋的章号未定")
        + (f"，第{f.plan_resolve_ch}章收）" if f.plan_resolve_ch else "）") for f in rows)


def _children(s: Session, parent_id: int) -> list[OutlineNode]:
    return list(s.exec(select(OutlineNode).where(OutlineNode.parent_id == parent_id).order_by(OutlineNode.order)))


def max_chapter_number(s: Session, book_id: int) -> int:
    v = s.exec(
        select(func.max(OutlineNode.order)).where(OutlineNode.book_id == book_id, OutlineNode.level == "chapter")
    ).one()
    return int(v or 0)


def _add_chapters(s: Session, book: Book, arc: OutlineNode, chapters: list[dict[str, Any]]) -> list[OutlineNode]:
    n = max_chapter_number(s, book.id or 0)
    out = []
    cheat = next(iter(common.cards(s, book.id or 0, "cheat")), None)
    recent = [b for b in chapter_beats_list(s, book.id or 0) if int(b.get("number") or 0) <= n][-MECHANISM_WINDOW:]
    for raw in chapters:
        n += 1
        beats = normalize_beats(raw if isinstance(raw, dict) else {}, n, book.chapter_words)
        beats = ensure_opening_beats(beats, n, cheat, book.tagline or "", recent)
        recent = [*recent, {**beats, "number": n}][-MECHANISM_WINDOW:]
        node = OutlineNode(
            book_id=book.id or 0, parent_id=arc.id, level="chapter", order=n, title=beats["title"],
            summary=f"{beats['goal']}；{beats['conflict']}".strip("；"), beats=beats, status="planned",
        )
        s.add(node)
        out.append(node)
    arc.status = "expanded"
    s.add(arc)
    return out


def generate_outline(book_id: int, ctx: JobContext) -> dict[str, Any]:
    from app.models.tables import Chapter

    gw = get_gateway()
    anchored_chapters = 0
    with common_session() as s:
        book = common.get_book(s, book_id)
        meta = {**common.kit_meta(s, book), "chapters_per_arc": CHAPTERS_PER_ARC}
        written = list(s.exec(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.number)))
        user = render(
            "outline", book_context=common.book_context(s, book), target_words=book.target_words,
            chapter_words=book.chapter_words,
        )
        if written:
            # v0.21 黄金三章先行倒序开书：已有开篇正文时，总纲、卷纲与后续章纲必须严格锚定已写内容
            anchored_chapters = len(written)
            anchor_lines = []
            for ch in written[:5]:
                brief = (ch.summary or "").strip() or (ch.content or "").strip()[:360].replace("\n", " ")
                anchor_lines.append(f"- 第{ch.number}章《{ch.title}》：{brief}")
            user += (
                "\n\n【已写成的黄金开篇（总纲、第一卷与后续章节必须严格承接以下已写正文，不得推翻设定与剧情）】\n"
                + "\n".join(anchor_lines)
                + f"\n（第 1–{written[-1].number} 章已落稿保留，第 1 弧的 chapters 请直接从第 {written[-1].number + 1} 章开始规划，不要重复规划已写章节。）"
            )
    user += research_notes("outline", user, book_id, ctx, 5)
    ctx.progress(10, "生成总纲、卷与前两弧" + ("（锚定已写开篇）" if anchored_chapters else ""))
    data = gw.chat_json("outline", system_prompt("outline"), user, meta=meta)
    if not isinstance(data, dict) or not data.get("volumes"):
        raise ValueError("大纲结构不完整（缺少 volumes）")
    issues = draft_audit(data)
    if issues:  # v0.18：开篇节奏体检不过（阻力原地打转、卖点拖太久），让规划模型按问题改一次
        ctx.progress(55, "开篇节奏体检不过，修正章细纲")
        fix = user + "\n\n【你上一版的规划】\n" + json.dumps(data, ensure_ascii=False)[:24000] + \
            "\n\n【程序体检发现的问题，这一版必须改掉】\n" + "\n".join(f"- {x}" for x in issues) + \
            "\n\n只改有问题的章细纲（和受影响的弧概要），其余照旧；输出完整 JSON，结构同上一版。"
        try:
            data2 = gw.chat_json("outline", system_prompt("outline"), fix, meta=meta)
            if isinstance(data2, dict) and data2.get("volumes") and data2.get("arcs"):
                data = data2
        except Exception:  # noqa: BLE001
            pass
    ctx.progress(70, "写入大纲")
    with common_session() as s:
        book = common.get_book(s, book_id)
        existing_nodes = common.outline_nodes(s, book_id)
        if any(n.locked for n in existing_nodes):
            raise Conflict("大纲里有锁定的节点，整体重新生成会覆盖它们；先解锁再重新生成")
        # 保留已成文章节对应的大纲节点（黄金三章先行时避免冲掉已写章节的绑定）
        written_chs = list(s.exec(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.number)))
        keep_by_num: dict[int, tuple[OutlineNode, Chapter]] = {}
        node_by_id = {n.id: n for n in existing_nodes}
        for ch in written_chs:
            nd = node_by_id.get(ch.outline_node_id) if ch.outline_node_id else None
            if nd is None:
                nd = next((n for n in existing_nodes if n.level == "chapter" and (n.chapter_id == ch.id or n.order == ch.number)), None)
            if nd is not None:
                keep_by_num[ch.number] = (nd, ch)
        keep_ids = {nd.id for nd, _ in keep_by_num.values()}
        for n in existing_nodes:
            if n.id not in keep_ids:
                s.delete(n)
        s.flush()
        bk = data.get("book") or {}
        root_summary = str(bk.get("summary", ""))
        if bk.get("promise"):
            root_summary += f"\n长期追读承诺：{bk['promise']}"
        promises = normalize_promises(bk.get("promises"))
        root = OutlineNode(book_id=book_id, level="book", order=1, title=str(bk.get("title") or book.title),
                           summary=root_summary, status="expanded", beats={"promises": promises} if promises else None)
        s.add(root)
        s.flush()
        vols: list[OutlineNode] = []
        for i, v in enumerate(data.get("volumes") or [], 1):
            node = OutlineNode(book_id=book_id, parent_id=root.id, level="volume", order=i,
                               title=str(v.get("title") or f"第{i}卷"), summary=str(v.get("summary", "")), status="planned")
            s.add(node)
            vols.append(node)
        s.flush()
        arc_count: dict[int, int] = {}
        chapters_total = 0
        first_arc: OutlineNode | None = None
        max_written = max((ch.number for ch in written_chs), default=0)
        raw_arcs = data.get("arcs") or []
        if not raw_arcs and written_chs:
            raw_arcs = [{"volume": 1, "title": "第1弧 黄金开篇", "summary": "承接已写开篇章节，继续推进主线。", "chapters": []}]
        for idx_a, a in enumerate(raw_arcs):
            vi = int(a.get("volume") or 1)
            vol = vols[min(max(vi, 1), len(vols)) - 1]
            arc_count[vol.id or 0] = arc_count.get(vol.id or 0, 0) + 1
            arc = OutlineNode(book_id=book_id, parent_id=vol.id, level="arc", order=arc_count[vol.id or 0],
                              title=str(a.get("title") or "未命名弧"), summary=str(a.get("summary", "")), status="planned")
            s.add(arc)
            s.flush()
            if first_arc is None:
                first_arc = arc
            vol.status = "expanded"
            s.add(vol)
            if idx_a == 0 and written_chs:
                # 先把已写章节挂回第 1 弧，保护已写正文与节点绑定
                for ch in written_chs:
                    if ch.number in keep_by_num:
                        kept, _ = keep_by_num[ch.number]
                        kept.parent_id = arc.id
                        kept.order = ch.number
                        kept.chapter_id = ch.id
                        kept.status = "written"
                        s.add(kept)
                    else:
                        kept = OutlineNode(
                            book_id=book_id, parent_id=arc.id, level="chapter", order=ch.number,
                            title=ch.title or f"第{ch.number}章", summary=(ch.summary or "")[:300],
                            beats={"number": ch.number, "title": ch.title or f"第{ch.number}章", "words": book.chapter_words},
                            status="written", chapter_id=ch.id,
                        )
                        s.add(kept)
                        s.flush()
                        ch.outline_node_id = kept.id
                        s.add(ch)
                    chapters_total += 1
                s.flush()
                # 只跳过模型里显式重复了已写章号（number <= max_written）或同标题的章节，避免误删从 max_written+1 起的新章
                written_titles = {(ch.title or "").strip() for ch in written_chs if (ch.title or "").strip()}
                cand: list[dict[str, Any]] = []
                for raw_c in (a.get("chapters") or []):
                    if not isinstance(raw_c, dict):
                        continue
                    try:
                        cnum = int(raw_c.get("number") or 0)
                    except (TypeError, ValueError):
                        cnum = 0
                    ctitle = str(raw_c.get("title") or "").strip()
                    if (cnum and cnum <= max_written) or (ctitle and ctitle in written_titles):
                        continue
                    cand.append(raw_c)
                chapters_total += len(_add_chapters(s, book, arc, cand))
            else:
                chapters_total += len(_add_chapters(s, book, arc, a.get("chapters") or []))
        if book.status in ("idea", "bible"):
            book.status = "writing" if written_chs else "outline"
        book.updated_at = utcnow()
        s.add(book)
        s.flush()
        pacing = pacing_audit(chapter_beats_list(s, book_id))
        s.commit()
    return {"volumes": len(vols), "chapters": chapters_total, "anchored_chapters": anchored_chapters, "pacing_warnings": pacing}


def _ensure_arc_for_batch(s: Session, book: Book, batch_title: str = "") -> OutlineNode:
    """找到或创建用于挂载新一批章纲的弧节点（没有大纲时自动创建最小总纲/第1卷/第1弧骨架）。"""
    nodes = common.outline_nodes(s, book.id or 0)
    root = next((n for n in nodes if n.level == "book"), None)
    if root is None:
        root = OutlineNode(book_id=book.id or 0, level="book", order=1, title=book.title or "总纲",
                           summary=book.tagline or book.premise or "", status="expanded")
        s.add(root)
        s.flush()
    vols = sorted([n for n in nodes if n.level == "volume"], key=lambda n: n.order)
    vol = vols[-1] if vols else None
    if vol is None:
        vol = OutlineNode(book_id=book.id or 0, parent_id=root.id, level="volume", order=1,
                          title="第一卷", summary=book.tagline or "开篇立局", status="expanded")
        s.add(vol)
        s.flush()
    arcs = sorted([n for n in nodes if n.level == "arc" and n.parent_id == vol.id], key=lambda n: n.order)
    if arcs:
        last_arc = arcs[-1]
        existing_chs = [n for n in nodes if n.level == "chapter" and n.parent_id == last_arc.id]
        if len(existing_chs) < 10 and not batch_title:
            return last_arc
    next_order = (arcs[-1].order + 1) if arcs else 1
    arc = OutlineNode(
        book_id=book.id or 0, parent_id=vol.id, level="arc", order=next_order,
        title=batch_title or f"第{next_order}弧", summary="批量重纲轻写章纲弧", status="planned",
    )
    s.add(arc)
    s.flush()
    return arc


def expand_chapters_batch(book_id: int, count: int, ctx: JobContext, instruction: str = "", heavy: bool = True,
                          arc_title: str = "") -> dict[str, Any]:
    """v0.21 批量生成千字起承转合章纲（默认 10 章，支持 1–20 章，重纲轻写 1:2 扩写比）。"""
    from app.services.skills_store import active_skills_for_book, render_skills_text

    count = max(1, min(20, int(count or 10)))
    gw = get_gateway()
    with common_session() as s:
        book = common.get_book(s, book_id)
        next_no = max_chapter_number(s, book_id) + 1
        all_beats = chapter_beats_list(s, book_id)
        recent = common.written_chapters(s, book_id)[-3:]
        opens = common.open_foreshadows(s, book_id)
        ledger = rhythm_ledger(all_beats, next_no)
        audit = pacing_audit(all_beats[-15:], opens, next_no)
        pt = promises_text(book_promises(s, book_id), next_no + count - 1)
        if pt:
            audit = [*audit, "卖点兑现表（到期的必须排进章细纲的 payoff）：\n" + pt]
        sk_plan = active_skills_for_book(s, book_id, "chapter_plan")
        sk_txt = render_skills_text(sk_plan, platform=getattr(book, "platform_style", "fanqie")) if sk_plan else ""
        heavy_note = (
            "【重纲轻写模式（千字详纲 → 2000字短章）】每章必须填满起承转合四拍（stage_qi / stage_cheng / stage_zhuan / stage_he，"
            "四拍合计 700–1000 字），写清具体画面、动作、对白冲突点、金手指触发与落袋收益，以及 core_scene、underlying_game、chapter_reward。"
        ) if heavy else ""
        extra_req = f"【作者本批附加要求】{instruction.strip()}" if instruction.strip() else ""
        req_lines = [
            f"请一次性规划第 {next_no} 章到第 {next_no + count - 1} 章共 {count} 章细纲（章号连续递增）。",
            heavy_note,
            extra_req,
            (f"【本书启用的章细纲技能】\n{sk_txt}" if sk_txt else ""),
        ]
        meta = {**common.kit_meta(s, book), "level": "arc", "existing": next_no - 1,
                "next_number": next_no, "chapters_per_arc": count, "number": next_no, "heavy": heavy}
        user = render(
            "expand", book_context=common.book_context(s, book), node_level="batch_chapters",
            node_title=arc_title or f"第{next_no}–{next_no + count - 1}章",
            node_summary=f"目标单章字数约 {book.chapter_words} 字，批量生成 {count} 章{'千字起承转合' if heavy else ''}细纲。",
            siblings="、".join(str(b.get("title") or "") for b in all_beats[-5:]) or "无",
            recent="\n".join(f"第{c.number}章《{c.title}》：{c.summary or (c.content or '')[:160]}" for c in recent) or "无",
            open_foreshadows=("\n".join(f"#{f.id} {f.desc}（第{f.planted_ch}章埋，{foreshadow_age_label(f, next_no)}）" for f in opens) or "无")
            + _planned_text(s, book_id),
            rhythm=ledger or "（尚无节奏标注）",
            pacing="\n".join(f"- {x}" for x in audit) or "（无）",
            instruction="\n".join(x for x in req_lines if x),
            schema=CHAPTER_SCHEMA,
        )
    ctx.progress(20, f"规划第 {next_no}–{next_no + count - 1} 章{'详纲' if heavy else '细纲'}")
    data = gw.chat_json("expand", system_prompt("expand"), user, meta=meta)
    if not isinstance(data, dict) or not data.get("chapters"):
        raise ValueError("批量章纲生成为空")
    raw_chs = list(data.get("chapters") or [])[:count]
    ctx.progress(80, "写入章纲")
    with common_session() as s:
        book = common.get_book(s, book_id)
        arc = _ensure_arc_for_batch(s, book, batch_title=arc_title)
        created = _add_chapters(s, book, arc, raw_chs)
        if book.status in ("idea", "bible"):
            book.status = "outline"
        book.updated_at = utcnow()
        s.add(book)
        s.flush()
        pacing = pacing_audit(chapter_beats_list(s, book_id)[-15:])
        s.commit()
        return {
            "arc_id": arc.id,
            "start_chapter": next_no,
            "end_chapter": next_no + len(created) - 1,
            "created": [c.id for c in created],
            "count": len(created),
            "heavy": heavy,
            "pacing_warnings": pacing,
        }


def expand_node(node_id: int, ctx: JobContext) -> dict[str, Any]:
    gw = get_gateway()
    with common_session() as s:
        node = s.get(OutlineNode, node_id)
        if node is None:
            raise NotFound("大纲节点不存在")
        book = common.get_book(s, node.book_id)
        kids = _children(s, node.id or 0)
        siblings = [n.title for n in s.exec(select(OutlineNode).where(OutlineNode.parent_id == node.parent_id)).all()] if node.parent_id else []
        recent = common.committed_chapters(s, book.id or 0)[-3:]
        opens = common.open_foreshadows(s, book.id or 0)
        next_no = max_chapter_number(s, book.id or 0) + 1
        all_beats = chapter_beats_list(s, book.id or 0)
        ledger = rhythm_ledger(all_beats, next_no)
        audit = pacing_audit(all_beats[-15:], opens, next_no)
        pt = promises_text(book_promises(s, book.id or 0), next_no + CHAPTERS_PER_ARC)
        if pt and node.level in ("arc", "volume"):
            audit = [*audit, "卖点兑现表（到期的必须排进章细纲的 payoff）：\n" + pt]
        meta = {**common.kit_meta(s, book), "level": node.level, "existing": len(kids),
                "next_number": max_chapter_number(s, book.id or 0) + 1, "chapters_per_arc": CHAPTERS_PER_ARC,
                "number": node.order}
        if node.level == "book":
            instruction, schema = "再规划 2 卷。", '{"volumes":[{"title":"","summary":""}]}'
        elif node.level == "volume":
            instruction, schema = "为这一卷规划接下来的 2 个弧。", '{"arcs":[{"title":"","summary":""}]}'
        elif node.level == "arc":
            instruction = f"为这一弧写 {CHAPTERS_PER_ARC} 章细纲（章号从 {meta['next_number']} 开始）。"
            schema = CHAPTER_SCHEMA
        else:
            instruction = "把这一章细纲补充完整。"
            schema = '{"beats":{"title":"","goal":"","conflict":"","outcome":"","payoff":"","characters":[],"location":"","foreshadow":[],"hook_end":""}}'
        user = render(
            "expand", book_context=common.book_context(s, book), node_level=node.level, node_title=node.title,
            node_summary=node.summary, siblings="、".join(siblings) or "无",
            recent="\n".join(f"第{c.number}章：{c.summary}" for c in recent) or "无",
            open_foreshadows=("\n".join(f"#{f.id} {f.desc}（第{f.planted_ch}章埋，{foreshadow_age_label(f, next_no)}）" for f in opens) or "无")
            + _planned_text(s, book.id or 0),
            rhythm=ledger or "（尚无节奏标注）",
            pacing="\n".join(f"- {x}" for x in audit) or "（无）",
            instruction=instruction, schema=schema,
        )
        from app.services.refs import refs_block  # v0.9.3 @引用

        rb = refs_block(s, book.id or 0, node.title or "", node.summary or "", json.dumps(node.beats or {}, ensure_ascii=False))
        user += ("\n\n" + rb) if rb else ""
        if node.level == "arc":  # v0.16：展开弧时带上所属卷的走向、前情卷回顾和作者导向（卷末复盘滚动调整的结果从这里落到章细纲）
            user += _arc_extra(s, node, next_no)
        level = node.level
    ctx.progress(15, f"展开{level}")
    data = gw.chat_json("expand", system_prompt("expand"), user, meta=meta)
    if not isinstance(data, dict):
        raise ValueError("展开结果不是 JSON 对象")
    if level == "arc":  # v0.17 爽点机制查重：和最近 5 章撞车就让模型换一次（只重试一次，仍撞车由 ensure_opening_beats 写进 must_avoid）
        dup = _new_mechanism_dupes(all_beats, data.get("chapters"), next_no)
        if dup:
            ctx.progress(30, "爽点机制和最近几章重复，换一版")
            fix = user + "\n\n程序查重：下面这些章的爽点机制和最近几章重复，换一种（换输家、换输法、换见证人或换收获），其余照旧：\n" + "\n".join(
                f"- 第{n}章「{mech[:40]}」和第{m}章重复" for n, m, mech in dup)
            try:
                data2 = gw.chat_json("expand", system_prompt("expand"), fix, meta={**meta, "dedupe": True})
                if isinstance(data2, dict) and data2.get("chapters"):
                    data = data2
            except ValueError:
                pass
    with common_session() as s:
        node = s.get(OutlineNode, node_id)
        assert node is not None
        book = common.get_book(s, node.book_id)
        created: list[OutlineNode] = []
        if level in ("book", "volume"):
            key, child_level = ("volumes", "volume") if level == "book" else ("arcs", "arc")
            start = len(_children(s, node.id or 0))
            for i, it in enumerate(data.get(key) or [], 1):
                c = OutlineNode(book_id=node.book_id, parent_id=node.id, level=child_level, order=start + i,
                                title=str(it.get("title") or ""), summary=str(it.get("summary", "")), status="planned")
                s.add(c)
                created.append(c)
            node.status = "expanded"
            s.add(node)
        elif level == "arc":
            created = _add_chapters(s, book, node, data.get("chapters") or [])
        else:
            if node.status == "written":
                raise Conflict("该章已写，不能再展开细纲")
            ensure_node_unlocked(node)
            beats = normalize_beats({**(node.beats or {}), **(data.get("beats") or {})}, node.order, book.chapter_words)
            node.beats = beats
            node.title = beats["title"]
            node.status = "expanded"
            s.add(node)
        if not created and level != "chapter":
            raise ValueError("展开结果为空")
        s.flush()
        pacing = pacing_audit(chapter_beats_list(s, node.book_id)[-15:]) if level in ("arc", "chapter") else []
        s.commit()
        return {"node_id": node_id, "created": [c.id for c in created], "pacing_warnings": pacing}


def _new_mechanism_dupes(old: list[dict[str, Any]], new: Any, next_no: int) -> list[tuple[int, int, str]]:
    items = [{**(c if isinstance(c, dict) else {}), "number": next_no + i} for i, c in enumerate(new if isinstance(new, list) else [])]
    lo = next_no
    return [d for d in mechanism_dupes([*old[-MECHANISM_WINDOW:], *items]) if d[0] >= lo]


def _arc_extra(s: Session, arc: OutlineNode, next_no: int) -> str:
    from app.services.autopilot import guidance_lines
    from app.services.context import volume_recaps

    out: list[str] = []
    vol = s.get(OutlineNode, arc.parent_id) if arc.parent_id else None
    if vol is not None and vol.level == "volume":
        p = (vol.beats or {}).get("wanben") or {}
        bits = [f"第{vol.order}卷 {vol.title}：{vol.summary}"]
        if p.get("crisis"):
            bits.append(f"本卷危机：{p['crisis']}")
        if p.get("closure"):
            bits.append(f"本卷收束：{p['closure']}")
        out.append("【所属卷】\n" + "\n".join(bits))
    recap, state, _ = volume_recaps(s, arc.book_id, next_no, budget=900)
    if recap:
        out.append("【前情卷回顾】\n" + recap + (("\n长期状态：\n" + state) if state else ""))
    guide = guidance_lines(s, arc.book_id, next_no)
    if guide:
        out.append("【作者导向】\n" + "\n".join(f"- {g}" for g in guide))
    return ("\n\n" + "\n\n".join(out)) if out else ""


def next_chapter_node(s: Session, book_id: int) -> OutlineNode | None:
    # v0.11：已经建了章（草稿/待审批，还没提交）的细纲节点也跳过——完本模式允许精修范围的章待审批时继续往后写；
    # 旧流程里有未提交章节时 write_next 会先拦下，行为不变
    from app.models.tables import Chapter

    used = select(Chapter.outline_node_id).where(Chapter.book_id == book_id, Chapter.outline_node_id != None)  # noqa: E711
    return s.exec(
        select(OutlineNode)
        .where(OutlineNode.book_id == book_id, OutlineNode.level == "chapter", OutlineNode.status != "written",
               OutlineNode.chapter_id == None, OutlineNode.id.notin_(used))  # type: ignore[union-attr]  # noqa: E711
        .order_by(OutlineNode.order)
    ).first()


def ensure_next_chapter_node(book_id: int, ctx: JobContext) -> int:
    """取下一个未写的章细纲；没有时按滚动规划自动展开下一弧（必要时先展开下一卷）。最多展开 3 步。"""
    for _ in range(3):
        with common_session() as s:
            node = next_chapter_node(s, book_id)
            if node is not None:
                return node.id or 0
            nodes = common.outline_nodes(s, book_id)
            if not nodes:
                raise Conflict("还没有大纲，请先生成大纲（没有细纲不许写正文）")
            vols = sorted([n for n in nodes if n.level == "volume"], key=lambda n: n.order)
            target: int | None = None
            for v in vols:
                arcs = sorted([n for n in nodes if n.level == "arc" and n.parent_id == v.id], key=lambda n: n.order)
                empty = [a for a in arcs if not any(c.parent_id == a.id for c in nodes if c.level == "chapter")]
                if empty:
                    target = empty[0].id
                    break
                if not arcs:
                    target = v.id
                    break
            if target is None:
                raise Conflict("大纲中的章节已全部写完，请先在大纲里展开新的卷或弧")
        ctx.progress(5, "滚动规划：自动展开下一层大纲")
        expand_node(target, ctx)
    raise Conflict("自动展开大纲失败，请手动展开")


def common_session():  # type: ignore[no-untyped-def]
    from app.db import session_scope

    return session_scope()


def node_plan_text(node: OutlineNode) -> str:
    b = dict(node.beats or {})
    b.pop("scenes", None)
    return json.dumps(b, ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ 节点概要：手动编辑留版本 / 按要求让 AI 重写 / 撤回

LEVEL_LABEL = {"book": "总纲", "volume": "卷", "arc": "弧", "chapter": "章细纲"}
LEVEL_RULE = {
    "book": "总纲概要写清主线、终局和读者追下去的长期期待。",
    "volume": "卷概要写清卷目标、主要冲突和卷末大爆点。",
    "arc": "弧概要写清弧目标和弧末高潮。",
    "chapter": "章概要写清本章戏剧问题和冲突。",
}
MAX_NODE_VERSIONS = 10
NODE_LOCKED_MSG = "这个大纲节点已锁定，AI 不能修改；先解锁再让 AI 改"


def ensure_node_unlocked(node: OutlineNode) -> None:
    if getattr(node, "locked", False):
        raise Conflict(NODE_LOCKED_MSG)


def push_node_version(node: OutlineNode, instruction: str) -> None:
    node.versions = [*(node.versions or []), {"title": node.title, "summary": node.summary, "beats": node.beats,
                                              "instruction": instruction[:200], "at": utcnow().isoformat()}][-MAX_NODE_VERSIONS:]


def suggest_node(node_id: int, instruction: str, route: str | None, ctx: JobContext) -> dict[str, Any]:
    """按要求重写一个节点的标题和概要，结果只是建议，作者预览后采纳。"""
    from app.services import tropes

    with common_session() as s:
        node = s.get(OutlineNode, node_id)
        if node is None:
            raise NotFound("大纲节点不存在")
        ensure_node_unlocked(node)
        book = common.get_book(s, node.book_id)
        parent = s.get(OutlineNode, node.parent_id) if node.parent_id else None
        sibs = [n for n in s.exec(select(OutlineNode).where(OutlineNode.parent_id == node.parent_id, OutlineNode.book_id == node.book_id)).all()
                if n.id != node.id] if node.parent_id else []
        kids = _children(s, node.id or 0)
        tl = tropes.tropes_for(s, book)
        user = render("outline_node", book_context=common.book_context(s, book), node_level=LEVEL_LABEL.get(node.level, node.level),
                      parent=f"{parent.title}：{parent.summary}" if parent else "（无）",
                      siblings="；".join(f"{n.title}" for n in sorted(sibs, key=lambda n: n.order)[:12]) or "（无）",
                      children="；".join(n.title for n in kids[:20]) or "（无）",
                      node_title=node.title, node_summary=node.summary or "（空）", instruction=instruction.strip(),
                      level_rule=LEVEL_RULE.get(node.level, ""))
        user += tropes.prompt_block(tl, instruction)
        from app.services.refs import refs_block  # v0.9.3 @引用

        rb = refs_block(s, book.id or 0, node.title or "", node.summary or "", instruction)
        user += ("\n\n" + rb) if rb else ""
        cur = {"title": node.title, "summary": node.summary}
        meta = {**cur, "level": node.level, "instruction": instruction, "banned_keywords": tropes.keywords(tl, instruction)}
    ctx.progress(30, f"AI 重写{LEVEL_LABEL.get(meta['level'], '')}")
    out = get_gateway().chat_json("outline_node", system_prompt("outline_node"), user, meta=meta, route=route)
    if not isinstance(out, dict) or not (out.get("summary") or out.get("title")):
        raise ValueError("模型没有给出修改")
    return {"node_id": node_id, "current": cur,
            "proposal": {"title": str(out.get("title") or cur["title"]).strip()[:80], "summary": str(out.get("summary") or cur["summary"]).strip()},
            "change": str(out.get("change") or "")[:120], "instruction": instruction.strip()}


def undo_node(node_id: int) -> OutlineNode:
    with common_session() as s:
        node = s.get(OutlineNode, node_id)
        if node is None:
            raise NotFound("大纲节点不存在")
        if not node.versions:
            raise Conflict("没有可以撤回的版本")
        prev = node.versions[-1]
        node.title, node.summary = prev.get("title", node.title), prev.get("summary", node.summary)
        if "beats" in prev and node.level == "chapter":
            node.beats = prev["beats"]
        node.versions = node.versions[:-1]
        s.add(node)
        s.commit()
        s.refresh(node)
        return node


def apply_nodes(book_id: int, items: list[dict[str, Any]], instruction: str) -> dict[str, Any]:
    """批量采纳节点修改（同步作品信息时用），每个节点各存一个旧版本。"""
    n = 0
    with common_session() as s:
        for it in items:
            node = s.get(OutlineNode, int(it.get("node_id") or 0))
            if node is None or node.book_id != book_id or node.locked:
                continue
            title = it.get("title")
            summary = it.get("summary")
            beats = it.get("beats")
            changed = (title is not None and title != node.title) or (summary is not None and summary != node.summary) or \
                      (isinstance(beats, dict) and node.level == "chapter" and beats != node.beats)
            if not changed:
                continue
            push_node_version(node, instruction or "同步修改")
            if title is not None:
                node.title = str(title)[:80]
            if summary is not None:
                node.summary = str(summary)
            if isinstance(beats, dict) and node.level == "chapter" and node.status != "written":
                node.beats = beats
            s.add(node)
            n += 1
        s.commit()
    return {"updated": n}
