"""v0.9 风向标日报：把一份榜单快照整理成模型输入 → 让模型写结构化日报 → schema 校验与容错 → 存 TrendReport。

scope：
- "overall"：四个总榜（男频阅读 / 男频新书 / 女频阅读 / 女频新书），每个榜按在读取前 N 本（跨题材去重）。
- "category:<gender>:<题材名>"：一个题材的阅读榜 + 新书榜，按名次取前 N 本。

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
TOP_N_OVERALL = 12
TOP_N_CATEGORY = 15
MOVERS_N = 5
ABSTRACT_CHARS = 120
LIMITS = {"hot_words": 8, "idea_hooks": 3, "open_directions": 5, "title_patterns": 6, "pitfalls": 6, "examples": 4}
# 套话：出现就记一条 warning（不删内容，给作者和调提示词的人看）
CLICHES = ("多元化", "百花齐放", "精品化", "内容为王", "持续发力", "值得关注", "不容小觑", "居高不下", "广大读者", "未来可期",
           "机遇与挑战", "不断创新", "强势崛起", "引领潮流")
_SCOPE_RX = re.compile(r"^category:(male|female):(.{1,20})$")


class ReportError(ValueError):
    pass


# ------------------------------------------------------------------ scope

def parse_scope(scope: str) -> tuple[str, str | None, str | None]:
    """→ (kind, gender, category)。kind 为 overall / category；格式不对抛 ReportError。"""
    scope = (scope or "overall").strip()
    if scope == "overall":
        return "overall", None, None
    m = _SCOPE_RX.match(scope)
    if not m or not m.group(2).strip():
        raise ReportError("scope 只能是 overall 或 category:<male|female>:<题材名>")
    return "category", m.group(1), m.group(2).strip()


def scope_boards(scope: str) -> list[tuple[str, str]]:
    kind, gender, _ = parse_scope(scope)
    return BOARD_ORDER if kind == "overall" else [(gender or "male", "read"), (gender or "male", "new")]


def scope_label(scope: str) -> str:
    kind, gender, cat = parse_scope(scope)
    return "四个总榜综合日报" if kind == "overall" else f"{GENDER_LABEL[gender or 'male']}「{cat}」题材日报（阅读榜 + 新书榜）"


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
    n = max(3, min(30, int(top_n or (TOP_N_OVERALL if kind == "overall" else TOP_N_CATEGORY))))
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
    return {"boards": boards, "movers": mv, "titles": list(dict.fromkeys(titles)), "board_names": list(boards),
            "boards_text": boards_text, "movers_text": "\n".join(mv_lines), "top_n": n}


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


def normalize_report(raw: Any, titles: list[str], board_names: list[str]) -> tuple[dict[str, Any], list[str]]:
    """把模型输出整理成固定 schema。返回（报告, warnings）。缺字段补空，类型不对尽量转，凭空的例子书名删掉。"""
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
                              "idea_hooks": hooks[:LIMITS["idea_hooks"]]})
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

    text = str(rep)
    hits = [c for c in CLICHES if c in text]
    if hits:
        warns.append("日报里有套话：" + "、".join(hits))
    if not rep["boards"] and not rep["hot_words"]:
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
    """POST 前的同步检查：scope 格式、有没有快照、题材在不在最新快照里。"""
    kind, gender, cat = parse_scope(scope)
    with session_scope() as s:
        snap = radar.latest_snapshot(s)
        if snap is None:
            raise LookupError("还没有榜单快照：先 POST /api/radar/refresh 刷新榜单")
        if kind == "category":
            row = s.exec(select(RankItem).where(RankItem.snapshot_id == snap.id, RankItem.gender == gender,
                                                RankItem.category == cat)).first()
            if row is None:
                raise LookupError(f"最新榜单里没有{GENDER_LABEL[gender or 'male']}「{cat}」这个题材")


def generate(scope: str, ctx: JobContext | None = None, top_n: int | None = None) -> dict[str, Any]:
    scope = (scope or "overall").strip()
    parse_scope(scope)
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
        board_names="、".join(board_names), board_enum="|".join(board_names),
    )
    progress(35, "模型撰写风向标日报")
    meta = {"scope": scope, "boards": inp["boards"], "movers": inp["movers"], "board_names": board_names, "titles": inp["titles"]}
    raw = get_gateway().chat_json("trend_report", system_prompt("trend_report"), user, meta=meta, temperature=0.5)
    progress(85, "校验日报（例子书名必须在榜上）")
    rep, warns = normalize_report(raw, inp["titles"], board_names)
    rep["warnings"] = warns
    rep["inputs"] = {"top_n": inp["top_n"], "books": len(inp["titles"]),
                     "boards": {k: len(v) for k, v in inp["boards"].items()},
                     "new_entries": {k: len(v["new"]) for k, v in inp["movers"].items()},
                     "prev_snapshot_id": prev_info["id"] if prev_info else None}
    with session_scope() as s:
        row = TrendReport(snapshot_id=snap_info["id"], scope=scope, report=rep, model=_model_label())
        s.add(row)
        s.commit()
        s.refresh(row)
        return report_out(s, row)


def latest_report(s: Session, scope: str = "overall", snapshot_id: int | None = None) -> TrendReport | None:
    q = select(TrendReport).where(TrendReport.scope == scope)
    if snapshot_id is not None:
        q = q.where(TrendReport.snapshot_id == snapshot_id)
    return s.exec(q.order_by(TrendReport.id.desc())).first()  # type: ignore[union-attr]


def list_reports(s: Session, limit: int = 10, scope: str | None = None) -> list[TrendReport]:
    q = select(TrendReport)
    if scope:
        q = q.where(TrendReport.scope == scope)
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
