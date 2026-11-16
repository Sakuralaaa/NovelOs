"""v0.9 风向标日报：把一份榜单快照整理成模型输入 → 让模型写结构化日报 → schema 校验与容错 → 存 TrendReport。

scope：
- "overall"：四个总榜（男频阅读 / 男频新书 / 女频阅读 / 女频新书），每个榜按在读取前 N 本（跨题材去重）。
- "board:<gender>:<read|new>"（v0.9.2）：只读这个频道的这一个总榜（跨题材按在读取前 N 本）。
- "category:<gender>:<read|new>:<题材名>"（v0.9.2）：一个题材的一个榜，按名次取前 N 本。
- "category:<gender>:<题材名>"：旧写法，保持 v0.9 行为（该题材阅读榜 + 新书榜两个榜），旧报告照常可查。
N 默认取配置 radar_report_top_n（30）。

程序负责“证据”：每本书的名次变化、新上榜、升幅最大都由代码对比上一份快照算出来；
模型给的例子书名必须是输入里真实出现的书名，否则删掉（热词 / 标题句式因此没有例子的整条作废）。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlmodel import Session, select

from app.db import session_scope
from app.jobs.manager import JobContext, find_active, submit
from app.llm.gateway import get_gateway, resolve_targets
from app.models.tables import RadarSnapshot, RankItem, TrendReport
from app.radar import service as radar
from app.skills.loader import render, system_prompt

log = logging.getLogger("novelos.radar")

GENDER_LABEL = {"male": "男频", "female": "女频"}
BOARD_LABEL = {"read": "阅读", "new": "新书"}
BOARD_ORDER: list[tuple[str, str]] = [("male", "read"), ("male", "new"), ("female", "read"), ("female", "new")]
BOARD_NAMES = tuple(GENDER_LABEL[g] + BOARD_LABEL[b] for g, b in BOARD_ORDER)  # 男频阅读 / 男频新书 / 女频阅读 / 女频新书
TOP_N_OVERALL = 30  # v0.9.2：默认值改由配置 radar_report_top_n 决定（30）；这两个常量只作兜底
TOP_N_CATEGORY = 30
TOP_N_MAX = 50
MOVERS_N = 5
ABSTRACT_CHARS = 80  # v0.9.2：每榜读的书多了，简介截短控制 token
LIMITS = {"hot_words": 8, "idea_hooks": 3, "open_directions": 5, "title_patterns": 6, "pitfalls": 6, "examples": 4,
          "inspirations": 6, "opening_hooks": 5, "plot_devices": 5, "risk_alerts": 6}
INSPIRATIONS_MIN = 4
# 套话：出现就记一条 warning（不删内容，给作者和调提示词的人看）
CLICHES = ("多元化", "百花齐放", "精品化", "内容为王", "持续发力", "值得关注", "不容小觑", "居高不下", "广大读者", "未来可期",
           "机遇与挑战", "不断创新", "强势崛起", "引领潮流")
_SCOPE_RX = re.compile(r"^category:(male|female):([^:]{1,20})$")
_SCOPE_CAT_BOARD_RX = re.compile(r"^category:(male|female):(read|new):([^:]{1,20})$")
_SCOPE_BOARD_RX = re.compile(r"^board:(male|female):(read|new)$")
SCOPE_HELP = "scope 只能是 overall、board:<male|female>:<read|new>、category:<male|female>:<read|new>:<题材名> 或 category:<male|female>:<题材名>"


class ReportError(ValueError):
    pass


# ------------------------------------------------------------------ scope

def scope_info(scope: str) -> dict[str, Any]:
    """→ {kind: overall|board|category, gender, board, category, canonical}。格式不对抛 ReportError。
    旧写法 category:<g>:<题材> 保持 v0.9 行为：board=None 表示阅读榜 + 新书榜。"""
    scope = (scope or "overall").strip()
    if scope == "overall":
        return {"kind": "overall", "gender": None, "board": None, "category": None, "canonical": "overall"}
    m = _SCOPE_BOARD_RX.match(scope)
    if m:
        return {"kind": "board", "gender": m.group(1), "board": m.group(2), "category": None, "canonical": scope}
    m = _SCOPE_CAT_BOARD_RX.match(scope)
    if m and m.group(3).strip():
        g, b, cat = m.group(1), m.group(2), m.group(3).strip()
        return {"kind": "category", "gender": g, "board": b, "category": cat, "canonical": f"category:{g}:{b}:{cat}"}
    m = _SCOPE_RX.match(scope)
    if m and m.group(2).strip() and not scope.startswith("board:"):
        g, cat = m.group(1), m.group(2).strip()
        return {"kind": "category", "gender": g, "board": None, "category": cat, "canonical": f"category:{g}:{cat}"}
    raise ReportError(SCOPE_HELP)


def parse_scope(scope: str) -> tuple[str, str | None, str | None]:
    """→ (kind, gender, category)。kind 为 overall / board / category；格式不对抛 ReportError。"""
    info = scope_info(scope)
    return info["kind"], info["gender"], info["category"]


def scope_aliases(scope: str) -> list[str]:
    """同一个 scope 的所有写法（查询最新 / 历史时互认）。目前只有首尾空白差异。"""
    info = scope_info(scope)
    out = [info["canonical"]]
    raw = (scope or "overall").strip()
    if raw not in out:
        out.append(raw)
    return out


def scope_boards(scope: str) -> list[tuple[str, str]]:
    info = scope_info(scope)
    if info["kind"] == "overall":
        return BOARD_ORDER
    g = info["gender"] or "male"
    return [(g, info["board"])] if info["board"] else [(g, "read"), (g, "new")]


def scope_label(scope: str) -> str:
    info = scope_info(scope)
    if info["kind"] == "overall":
        return "四个总榜综合日报"
    if info["board"] is None:
        return f"{GENDER_LABEL[info['gender'] or 'male']}「{info['category']}」题材日报（阅读榜 + 新书榜）"
    name = GENDER_LABEL[info["gender"] or "male"] + BOARD_LABEL[info["board"]]
    if info["kind"] == "board":
        return f"{name}榜日报（只看这一个榜）"
    return f"{GENDER_LABEL[info['gender'] or 'male']}「{info['category']}」题材{BOARD_LABEL[info['board'] or 'read']}榜日报"


def default_top_n() -> int:
    from app.config import get_settings

    try:
        with session_scope() as s:
            v = radar.get_report_config(s).get("radar_report_top_n")
    except Exception:  # noqa: BLE001
        v = None
    return int(v or get_settings().radar_report_top_n)


# ------------------------------------------------------------------ 输入整理（纯数据，便于测试）

def _fmt_read(n: int) -> str:
    return f"{n / 10000:.1f}万" if n >= 10000 else str(n)


def _change(it: dict[str, Any]) -> str:
    if it.get("is_new"):
        return "新上榜"
    d = int(it.get("rank_change") or 0)
    return f"↑{d}" if d > 0 else (f"↓{-d}" if d < 0 else "持平")


def item_line(it: dict[str, Any]) -> str:
    tags = "、".join(t for t in (it.get("tags") or []) if t and t != it.get("category"))[:30] or "无"
    abstract = re.sub(r"\s+", " ", str(it.get("abstract") or ""))[:ABSTRACT_CHARS]
    return (f"《{it['title']}》｜{it.get('category') or '其他'}｜{tags}｜在读{_fmt_read(int(it.get('read_count') or 0))}"
            f"｜第{it.get('rank')}名（{_change(it)}）｜{abstract}")


def annotate(cur: list[dict[str, Any]], prev: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给本期每本书标上名次变化：优先用上一份快照对比（同榜、同题材）；没有上一份时用番茄返回的 rank_diff。"""
    prev_rank = {radar.rank_key(p): int(p["rank"]) for p in prev}
    out = []
    for it in cur:
        it = {**it, "board": radar.board_of(it)}
        if prev:
            pr = prev_rank.get(radar.rank_key(it))
            it["is_new"] = pr is None
            it["rank_change"] = 0 if pr is None else pr - int(it["rank"])
        else:
            it["is_new"] = False
            it["rank_change"] = int(it.get("rank_diff") or 0)
        out.append(it)
    return out


def _dedupe_by_book(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for it in items:
        if it["book_id_ext"] in seen:
            continue
        seen.add(it["book_id_ext"])
        out.append(it)
    return out


def select_board_items(items: list[dict[str, Any]], gender: str, board: str, category: str | None, top_n: int) -> list[dict[str, Any]]:
    rows = [i for i in items if i["gender"] == gender and i["board"] == board and (category is None or i.get("category") == category)]
    if category is None:  # 总榜：没有跨题材名次，按在读排（同一本书上多个题材榜只留一次）
        rows.sort(key=lambda i: (-int(i.get("read_count") or 0), int(i["rank"])))
    else:
        rows.sort(key=lambda i: int(i["rank"]))
    return _dedupe_by_book(rows)[:top_n]


def movers(items: list[dict[str, Any]], gender: str, board: str, category: str | None, n: int = MOVERS_N) -> dict[str, list[dict[str, Any]]]:
    rows = [i for i in items if i["gender"] == gender and i["board"] == board and (category is None or i.get("category") == category)]
    new = _dedupe_by_book(sorted([i for i in rows if i.get("is_new")], key=lambda i: int(i["rank"])))[:n]
    up = _dedupe_by_book(sorted([i for i in rows if not i.get("is_new") and int(i.get("rank_change") or 0) > 0],
                                key=lambda i: (-int(i["rank_change"]), int(i["rank"]))))[:n]
    return {"new": new, "up": up}


def build_input(cur: list[dict[str, Any]], prev: list[dict[str, Any]], scope: str, top_n: int | None = None) -> dict[str, Any]:
    """→ {boards:{名:[item]}, movers:{名:{new,up}}, titles:[全部出现过的书名], board_names:[...] , boards_text, movers_text}"""
    kind, _, category = parse_scope(scope)
    n = max(3, min(TOP_N_MAX, int(top_n or default_top_n())))
    items = annotate(cur, prev)
    boards: dict[str, list[dict[str, Any]]] = {}
    mv: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for g, b in scope_boards(scope):
        name = GENDER_LABEL[g] + BOARD_LABEL[b]
        boards[name] = select_board_items(items, g, b, category, n)
        mv[name] = movers(items, g, b, category)
    titles: list[str] = []
    for name in boards:
        titles += [i["title"] for i in boards[name]]
        titles += [i["title"] for k in ("new", "up") for i in mv[name][k]]
    boards_text = "\n\n".join(
        f"【{name}榜】" + ("（本期没有数据）" if not rows else "\n" + "\n".join(item_line(i) for i in rows))
        for name, rows in boards.items())
    mv_lines: list[str] = []
    for name, m in mv.items():
        if not prev and not any(int(i.get("rank_change") or 0) for i in m["up"]):
            mv_lines.append(f"【{name}榜】没有上一份快照，无法对比")
            continue
        new = "、".join(f"《{i['title']}》（{i.get('category')}，第{i['rank']}名）" for i in m["new"]) or "无"
        up = "、".join(f"《{i['title']}》（{i.get('category')}，↑{i['rank_change']}到第{i['rank']}名）" for i in m["up"]) or "无"
        mv_lines.append(f"【{name}榜】新上榜：{new}\n　升幅最大：{up}")
    refs: dict[str, str] = {}
    for name in boards:
        for i in boards[name] + [i for k in ("new", "up") for i in mv[name][k]]:
            refs.setdefault(i["title"], str(i.get("abstract") or ""))
    books_read = len({i["book_id_ext"] for rows in boards.values() for i in rows})
    return {"boards": boards, "movers": mv, "titles": list(dict.fromkeys(titles)), "board_names": list(boards),
            "boards_text": boards_text, "movers_text": "\n".join(mv_lines), "top_n": n, "books_read": books_read,
            "refs": [{"title": t, "abstract": a} for t, a in refs.items()]}


# ------------------------------------------------------------------ 输出校验与容错

def _s(v: Any, n: int = 300) -> str:
    if isinstance(v, (list, tuple)):
        v = "；".join(str(x) for x in v if x)
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _strip_title(t: Any) -> str:
    return str(t or "").strip().strip("《》<>「」“”\"' ").strip()


def _match_titles(raw: Any, titles: list[str]) -> list[str]:
    """例子书名只留输入里真实存在的（允许模型漏掉书名号或多了空格）。"""
    if isinstance(raw, str):
        raw = re.split(r"[、，,；;]\s*", raw)
    if not isinstance(raw, list):
        return []
    norm = {re.sub(r"\s+", "", t): t for t in titles}
    out: list[str] = []
    for x in raw:
        key = re.sub(r"\s+", "", _strip_title(x))
        if key in norm and norm[key] not in out:
            out.append(norm[key])
    return out[:LIMITS["examples"]]


def _board_name(v: Any, allowed: list[str]) -> str | None:
    s = re.sub(r"\s|榜", "", str(v or ""))
    for name in allowed:
        if s == name or s == name.replace("频", ""):
            return name
    return None


def _str_list(v: Any, k: int, n: int) -> list[str]:
    if isinstance(v, str):
        v = [x for x in re.split(r"\n+", v) if x.strip()]
    return [d for d in (_s(x, n) for x in (v if isinstance(v, list) else []) if isinstance(x, (str, list))) if d][:k]


def _inspirations(raw: Any, titles: list[str], board_names: list[str], refs: list[dict[str, Any]] | None,
                  warns: list[str]) -> list[dict[str, Any]]:
    """灵感卡：和榜上书重名的删；和榜上书名+简介有连续 8 字相同（v0.7 n-gram）的删。"""
    from app.services.imitate import OVERLAP_N, overlap_segments

    title_keys = {re.sub(r"\s+", "", t) for t in titles}
    ref_texts = [(str(r.get("title") or ""), f"{r.get('title') or ''}\n{r.get('abstract') or ''}") for r in (refs or [])]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for x in raw if isinstance(raw, list) else []:
        if not isinstance(x, dict):
            continue
        title = _strip_title(x.get("title"))[:30]
        if not title or title in seen:
            continue
        if re.sub(r"\s+", "", title) in title_keys:
            warns.append(f"灵感《{title}》和榜上书重名，已删")
            continue
        sp = x.get("selling_points")
        if isinstance(sp, str):
            sp = re.split(r"[；;\n]+", sp)
        card = {"title": title, "logline": _s(x.get("logline") or x.get("pitch"), 120), "protagonist": _s(x.get("protagonist"), 80),
                "mechanism": _s(x.get("mechanism"), 120), "opening": _s(x.get("opening"), 160),
                "selling_points": [p for p in (_s(y, 30) for y in (sp if isinstance(sp, list) else [])) if p][:3]}
        b = _board_name(x.get("board"), board_names) if x.get("board") else None
        if b:
            card["board"] = b
        text = "\n".join([card["title"], card["logline"], card["protagonist"], card["mechanism"], card["opening"], *card["selling_points"]])
        hit = next(((t, segs) for t, ref in ref_texts if (segs := overlap_segments(text, ref))), None)
        if hit:
            warns.append(f"灵感《{title}》和榜上《{hit[0]}》的书名/简介有 {len(hit[1])} 处连续 {OVERLAP_N} 字相同（{hit[1][0][:20]}），已删")
            continue
        seen.add(title)
        out.append(card)
    return out[:LIMITS["inspirations"]]


def normalize_report(raw: Any, titles: list[str], board_names: list[str],
                     refs: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], list[str]]:
    """把模型输出整理成固定 schema。返回（报告, warnings）。缺字段补空，类型不对尽量转，凭空的例子书名删掉。
    refs：[{title, abstract}] 榜上书（v0.9.2 灵感卡查重用）；不传时只查重名。"""
    warns: list[str] = []
    if isinstance(raw, list):  # 有的模型直接给数组：当成 boards
        raw = {"boards": raw}
    if not isinstance(raw, dict):
        raise ReportError("模型没有给出 JSON 对象")
    rep: dict[str, Any] = {"hot_words": [], "boards": [], "open_directions": [], "title_patterns": [], "pitfalls": []}

    for h in raw.get("hot_words") or []:
        if isinstance(h, str):
            h = {"word": h}
        if not isinstance(h, dict) or not _s(h.get("word"), 20):
            continue
        ex = _match_titles(h.get("examples"), titles)
        if not ex:
            warns.append(f"热词「{_s(h.get('word'), 20)}」没有榜上真实书名作例子，已删")
            continue
        rep["hot_words"].append({"word": _s(h.get("word"), 20), "why": _s(h.get("why"), 120), "examples": ex})
    rep["hot_words"] = rep["hot_words"][:LIMITS["hot_words"]]

    seen_boards: set[str] = set()
    for b in raw.get("boards") or []:
        if not isinstance(b, dict):
            continue
        name = _board_name(b.get("board"), board_names)
        if name is None or name in seen_boards:
            continue
        seen_boards.add(name)
        hooks = []
        for x in b.get("idea_hooks") or []:
            if isinstance(x, str):
                t, _, p = x.partition("｜") if "｜" in x else x.partition("|")
                x = {"title": t, "pitch": p}
            if isinstance(x, dict) and _strip_title(x.get("title")):
                title = _strip_title(x.get("title"))[:30]
                if title in titles:
                    warns.append(f"灵感切口《{title}》和榜上书重名，已删")
                    continue
                hooks.append({"title": title, "pitch": _s(x.get("pitch"), 120)})
        rep["boards"].append({"board": name, "overview": _s(b.get("overview")), "reader_mood": _s(b.get("reader_mood")),
                              "opportunity": _s(b.get("opportunity")), "writing_tips": _s(b.get("writing_tips")),
                              "risks": _s(b.get("risks")), "idea_hooks": hooks[:LIMITS["idea_hooks"]]})
    rep["boards"].sort(key=lambda b: board_names.index(b["board"]))
    for name in board_names:
        if name not in seen_boards:
            warns.append(f"模型没有写「{name}」榜")

    rep["open_directions"] = [d for d in (_s(x, 160) for x in (raw.get("open_directions") or []) if isinstance(x, (str, list))) if d][:LIMITS["open_directions"]]
    for p in raw.get("title_patterns") or []:
        if isinstance(p, str):
            p = {"pattern": p}
        if not isinstance(p, dict) or not _s(p.get("pattern"), 40):
            continue
        ex = _match_titles(p.get("examples"), titles)
        if not ex:
            warns.append(f"标题句式「{_s(p.get('pattern'), 40)}」没有从真实书名归纳的例子，已删")
            continue
        rep["title_patterns"].append({"pattern": _s(p.get("pattern"), 40), "examples": ex})
    rep["title_patterns"] = rep["title_patterns"][:LIMITS["title_patterns"]]
    rep["pitfalls"] = [d for d in (_s(x, 120) for x in (raw.get("pitfalls") or []) if isinstance(x, (str, list))) if d][:LIMITS["pitfalls"]]

    # ---- v0.9.2：定调、灵感卡、开篇钩子、剧情装置、写作建议、风险提醒
    rep["headline"] = _s(raw.get("headline"), 40)
    rep["summary"] = _s(raw.get("summary"), 300)
    rep["inspirations"] = _inspirations(raw.get("inspirations"), titles, board_names, refs, warns)
    if len(rep["inspirations"]) < INSPIRATIONS_MIN:
        warns.append(f"灵感卡只有 {len(rep['inspirations'])} 条（要求 {INSPIRATIONS_MIN}–{LIMITS['inspirations']} 条）")
    rep["opening_hooks"] = _str_list(raw.get("opening_hooks"), LIMITS["opening_hooks"], 100)
    devices: list[dict[str, str]] = []
    for d in raw.get("plot_devices") or []:
        if isinstance(d, str):
            nm, _, desc = d.partition("：") if "：" in d else d.partition(":")
            d = {"name": nm, "desc": desc}
        if isinstance(d, dict) and _s(d.get("name"), 20):
            devices.append({"name": _s(d.get("name"), 20), "desc": _s(d.get("desc") or d.get("description"), 160)})
    rep["plot_devices"] = devices[:LIMITS["plot_devices"]]
    rep["writing_advice"] = _s(raw.get("writing_advice"), 400)
    rep["risk_alerts"] = _str_list(raw.get("risk_alerts"), LIMITS["risk_alerts"], 120)
    # 灵感切口兼容：模型没给的榜，用归到这个榜的灵感卡派生（title / pitch=logline）
    for b in rep["boards"]:
        if not b["idea_hooks"]:
            b["idea_hooks"] = [{"title": x["title"], "pitch": x["logline"]} for x in rep["inspirations"]
                               if x.get("board") == b["board"]][:LIMITS["idea_hooks"]]
    if len(rep["boards"]) == 1 and not rep["boards"][0]["idea_hooks"]:  # 单榜日报：灵感卡都算这个榜的
        rep["boards"][0]["idea_hooks"] = [{"title": x["title"], "pitch": x["logline"]} for x in rep["inspirations"]][:LIMITS["idea_hooks"]]

    text = str(rep)
    hits = [c for c in CLICHES if c in text]
    if hits:
        warns.append("日报里有套话：" + "、".join(hits))
    if not rep["boards"] and not rep["hot_words"] and not rep["inspirations"]:
        raise ReportError("模型输出里没有可用的榜单分析或热词")
    return rep, warns


# ------------------------------------------------------------------ 生成 / 查询

def _model_label(role: str = "planner") -> str:
    with session_scope() as s:
        ts = resolve_targets(s, role)
    return f"{ts[0].name}/{ts[0].model}" if ts else "mock"


def _snap_brief(sn: RadarSnapshot | None) -> dict[str, Any] | None:
    if sn is None:
        return None
    from app.api.schemas import iso

    return {"id": sn.id, "taken_at": iso(sn.taken_at), "source": sn.source, "version": sn.version, "items_count": sn.items_count}


def _snapshot_dicts(s: Session, snapshot_id: int) -> list[dict[str, Any]]:
    return [i.model_dump() for i in radar.snapshot_items(s, snapshot_id, dedupe=False)]


def check_can_generate(scope: str) -> None:
    """POST 前的同步检查：scope 格式、有没有快照、题材 / 榜在不在最新快照里。"""
    info = scope_info(scope)
    with session_scope() as s:
        snap = radar.latest_snapshot(s)
        if snap is None:
            raise LookupError("还没有榜单快照：先 POST /api/radar/refresh 刷新榜单")
        if info["kind"] == "overall":
            return
        q = select(RankItem.board).where(RankItem.snapshot_id == snap.id, RankItem.gender == info["gender"])
        if info["kind"] == "category":
            q = q.where(RankItem.category == info["category"])
        boards = {radar.board_of({"board": b}) for b in s.exec(q.distinct())}
        g = GENDER_LABEL[info["gender"] or "male"]
        if info["kind"] == "category" and not boards:
            raise LookupError(f"最新榜单里没有{g}「{info['category']}」这个题材")
        if info["board"] is not None and info["board"] not in boards:
            where = f"「{info['category']}」" if info["kind"] == "category" else ""
            raise LookupError(f"最新榜单里没有{g}{where}{BOARD_LABEL[info['board'] or 'read']}榜")


def generate(scope: str, ctx: JobContext | None = None, top_n: int | None = None) -> dict[str, Any]:
    scope = (scope or "overall").strip()
    scope_info(scope)
    progress = ctx.progress if ctx else (lambda *a, **k: None)
    with session_scope() as s:
        snap = radar.latest_snapshot(s)
        if snap is None:
            raise ReportError("还没有榜单快照：先刷新榜单")
        prev_snap = radar.latest_snapshot(s, 1)
        cur = _snapshot_dicts(s, snap.id or 0)
        prev = _snapshot_dicts(s, prev_snap.id or 0) if prev_snap else []
        snap_info, prev_info = _snap_brief(snap), _snap_brief(prev_snap)
    progress(15, "整理榜单：前 N 本、新上榜、升幅最大")
    inp = build_input(cur, prev, scope, top_n)
    if not inp["titles"]:
        raise ReportError("这份快照里没有可分析的书")
    board_names = inp["board_names"]
    user = render(
        "trend_report", scope_label=scope_label(scope),
        snapshot_label=f"#{snap_info['id']} {snap_info['taken_at'] or ''}（版本 {snap_info['version'] or '无'}）",
        source_label={"web": "番茄网页榜单", "app": "番茄 App 榜单", "mock": "示例数据（不是真实榜单）"}.get(snap_info["source"], snap_info["source"]),
        prev_label=f"#{prev_info['id']}" if prev_info else "无",
        boards_text=inp["boards_text"], movers_text=inp["movers_text"],
        board_names="、".join(board_names), board_enum="|".join(board_names), top_n=inp["top_n"],
    )
    progress(35, "模型撰写风向标日报")
    meta = {"scope": scope, "boards": inp["boards"], "movers": inp["movers"], "board_names": board_names, "titles": inp["titles"],
            "refs": inp["refs"]}
    raw = get_gateway().chat_json("trend_report", system_prompt("trend_report"), user, meta=meta, temperature=0.5)
    progress(85, "校验日报（例子书名必须在榜上）")
    rep, warns = normalize_report(raw, inp["titles"], board_names, inp["refs"])
    rep["warnings"] = warns
    rep["meta"] = {"scope": scope, "top_n": inp["top_n"], "books_read": inp["books_read"], "abstract_chars": ABSTRACT_CHARS}
    rep["inputs"] = {"top_n": inp["top_n"], "books": len(inp["titles"]), "books_read": inp["books_read"],
                     "boards": {k: len(v) for k, v in inp["boards"].items()},
                     "new_entries": {k: len(v["new"]) for k, v in inp["movers"].items()},
                     "prev_snapshot_id": prev_info["id"] if prev_info else None}
    with session_scope() as s:
        row = TrendReport(snapshot_id=snap_info["id"], scope=scope, report=rep, model=_model_label())
        s.add(row)
        s.commit()
        s.refresh(row)
        return report_out(s, row)


def _scope_filter(scope: str) -> Any:
    try:
        names = scope_aliases(scope)
    except ReportError:
        names = [scope]
    return TrendReport.scope.in_(names)  # type: ignore[attr-defined]


def latest_report(s: Session, scope: str = "overall", snapshot_id: int | None = None) -> TrendReport | None:
    q = select(TrendReport).where(_scope_filter(scope))
    if snapshot_id is not None:
        q = q.where(TrendReport.snapshot_id == snapshot_id)
    return s.exec(q.order_by(TrendReport.id.desc())).first()  # type: ignore[union-attr]


def list_reports(s: Session, limit: int = 10, scope: str | None = None) -> list[TrendReport]:
    q = select(TrendReport)
    if scope:
        q = q.where(_scope_filter(scope))
    return list(s.exec(q.order_by(TrendReport.id.desc()).limit(max(1, min(50, limit)))))  # type: ignore[union-attr]


def report_out(s: Session, r: TrendReport, with_report: bool = True) -> dict[str, Any]:
    from app.api.schemas import iso

    latest = radar.latest_snapshot(s)
    out: dict[str, Any] = {"id": r.id, "snapshot_id": r.snapshot_id, "scope": r.scope, "created_at": iso(r.created_at),
                           "model": r.model, "stale": latest is not None and latest.id != r.snapshot_id,
                           "snapshot": _snap_brief(s.get(RadarSnapshot, r.snapshot_id))}
    if with_report:
        out["report"] = r.report or {}
    else:
        rep = r.report or {}
        out["hot_words"] = [h.get("word") for h in rep.get("hot_words") or []]
    return out


def report_ref(scope: str) -> str:
    return f"trend_report:{scope}"


def submit_report(scope: str = "overall", top_n: int | None = None) -> Any:
    """提交日报任务；同一 scope 已有排队/运行中的就直接返回它。"""
    running = find_active("radar_report", report_ref(scope))
    if running is not None:
        return running
    return submit("radar_report", lambda ctx: generate(scope, ctx, top_n), ref=report_ref(scope))
