"""v0.10 同人创作：原著资料（设定卡）、同人书、上下文注入、OOC 检查、与原著的 8 字重合检查。

- 原文不入库：导入的原著只在任务内存里用一次，库里只存提炼出的设定卡 + 所取片段的 8 字 crc32 指纹（复用 v0.9.3 拆书指纹）。
- 设定卡除口癖外都要求「自己的话」：和原文有连续 8 字相同的字段清空/条目删除，记 warnings。
- 同人书：Book.fanfic = {source_id, fidelity, direction, ...}；建书前必须确认版权声明（copyright_ack=true），书上存确认时间。
- 上下文：common.book_context 末尾调用 context_block()，大纲、写章、设定等所有带书设定的提示词都会带上原著卡摘要 + 遵循规则。
- OOC：run_ooc() 走模型逐角色打分；ooc_block() 是给审稿用的确定性函数（读已存的 OOC 结果 + 口癖滥用 + 原著重合），不调模型。
"""

from __future__ import annotations

import re
import zlib
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway, is_mock_mode
from app.models.tables import Book, Card, Chapter, FanficSource
from app.services.common import Conflict, NotFound
from app.services import common
from app.services.fanfic_directions import DIRECTION_BY_ID, DIRECTION_IDS, FIDELITY, FIDELITIES, OC_TYPES, POVS
from app.services.imitate import OVERLAP_N, _norm
from app.services.teardown_ws import _leaves, _s, _strs, fingerprint, fp_hits
from app.skills.loader import render, system_prompt

MAX_BYTES = 30 * 1024 * 1024  # 导入上限 30MB
FP_CHARS = 200_000  # 最多取用的原文字数（提炼 + 指纹），超出部分按重点/开头/均匀抽样取
PROMPT_CHUNK = 12_000  # 每轮提炼进提示词的字数
DEPTHS = {"quick": 1, "standard": 2, "deep": 4}
SOURCES = ("paste", "txt", "search")  # v0.11.1 search：联网取材（只填作品名）
CARD_PARTS = ("characters", "world", "factions", "timeline", "scenes")
IMPORT_PARTS = ("characters", "factions", "world", "locations")
MAX_CHARS_CARDS = 30
OOC_TYPES = {"speech": "言行", "catchphrase": "口癖", "relation": "关系", "ability": "能力越界", "timeline": "时间线", "world_rule": "世界规则"}
PENALTY = {"high": 25, "mid": 10, "low": 3}
OOC_CONTENT = 12_000
CATCHPHRASE_MAX = 3  # 同一口癖一章出现超过这个次数算滥用
CONTEXT_BUDGET = 2400

_NAME_RE = re.compile(r"([\u4e00-\u9fa5]{2,3})(?:笑道|问道|说道|喝道|冷笑|低声|说|道|问)")
_STOP = set("我们 你们 他们 她们 它们 自己 大家 众人 一边 只是 知道 心中 心里 忍不住 不由 于是 然后 这时 此时 那人 有人 对方 少年 少女 男子 女子 老者 "
            "众弟子 什么 怎么 这么 那么 如此 不过 但是 可是 而是 还是 就是 便是 却是 于是 突然 忽然 微微 淡淡 轻轻 缓缓 冷冷 笑着 摇头 点头 开口 继续 "
            "连忙 急忙 赶紧 立刻 只好 低头 抬头 转身 回头 听到 看到".split())
_SENT_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?")


class FanficError(ValueError):
    def __init__(self, msg: str, status: int = 400) -> None:
        super().__init__(msg)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(dt: datetime | None) -> str | None:
    from app.api.schemas import iso

    return iso(dt)


# ------------------------------------------------------------------ 导入与取材

def decode_txt(raw: bytes) -> str:
    if len(raw) > MAX_BYTES:
        raise FanficError("文件超过 30MB，请只保留需要的部分再导入", 413)
    for enc in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise FanficError("无法识别文件编码，请转成 UTF-8 或 GBK 的 TXT")


def check_input(source: str, text: str | None, depth: str = "standard", title: str | None = None, web: bool = False) -> None:
    """同步预检（路由里调，Job 里再调一次）。source=search 只要作品名；web=True（原文 + 联网补充）也要作品名。"""
    if source not in SOURCES:
        raise FanficError("source 只能是 paste / txt / search", 422)
    if depth not in DEPTHS:
        raise FanficError("depth 只能是 quick / standard / deep", 422)
    if source == "search":
        if not (title or "").strip():
            raise FanficError("联网取材请填写作品名", 422)
        require_search()
        return
    if web:
        if not (title or "").strip():
            raise FanficError("联网补充需要填写原著名（作品名），用来检索", 422)
        require_search()
    body = (text or "").strip()
    if not body:
        raise FanficError("请粘贴或上传原著文本")
    if len(body.encode("utf-8")) > MAX_BYTES:
        raise FanficError("原文超过 30MB，请只保留需要的部分再导入", 413)
    if len(_norm(body)) < 200:
        raise FanficError("原文太短（少于 200 字），提炼不出设定")


def guess_names(text: str, k: int = 12) -> list[str]:
    """程序猜高频人名（「X说/道/问」前的 2–3 字），只作提示与 mock 用。"""
    cnt: Counter[str] = Counter()
    for m in _NAME_RE.finditer(text[:FP_CHARS]):
        w = m.group(1)
        if w in _STOP or w[:2] in _STOP or w[-2:] in _STOP or w[-1] in "知都也就又还在着了的":
            continue
        cnt[w] += 1
    # 三字名里含两字高频名的，归到两字名（「林川说」「林川道」 vs 「向林川」）
    out: list[str] = []
    for w, c in cnt.most_common(k * 3):
        if c < 2:
            break
        if any(o in w or w in o for o in out):
            continue
        out.append(w)
        if len(out) >= k:
            break
    return out


def select_material(text: str, focus: list[str], depth: str) -> tuple[str, list[str]]:
    """返回（取用的原文，各轮提示词片段）。超出 FP_CHARS 时：重点段落优先，其次开头，余量均匀抽样。"""
    paras = [p.strip() for p in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if p.strip()]
    total = sum(len(p) for p in paras)
    focus = [f for f in focus if f]
    if total <= FP_CHARS:
        chosen = list(range(len(paras)))
    else:
        picked: set[int] = set()
        used = 0

        def take(i: int, cap: int) -> bool:
            nonlocal used
            if i in picked:
                return True
            if used + len(paras[i]) > cap:
                return False
            picked.add(i)
            used += len(paras[i])
            return True

        if focus:  # 1. 重点段落（含作者指定的角色名/关键词），最多 45%
            for i, p in enumerate(paras):
                if any(f in p for f in focus):
                    take(i, int(FP_CHARS * 0.45))
        head_cap = used + int(FP_CHARS * 0.35)  # 2. 开头连续取 35%（人物登场、世界观交代多在开头）
        for i in range(len(paras)):
            if not take(i, head_cap):
                break
        rest = [i for i in range(len(paras)) if i not in picked]  # 3. 余量在后文均匀抽样
        if rest and used < FP_CHARS:
            need = max(1, (FP_CHARS - used) // max(1, total // len(paras)))
            for i in rest[::max(1, len(rest) // need)]:
                take(i, FP_CHARS)
        chosen = sorted(picked)
    selected = [paras[i] for i in chosen]
    n = DEPTHS[depth]
    chunks: list[str] = []
    size = max(1, len(selected) // n + (1 if len(selected) % n else 0))
    for k in range(n):
        seg = selected[k * size:(k + 1) * size]
        if not seg:
            break
        idx = [i for i, p in enumerate(seg) if focus and any(f in p for f in focus)] + list(range(len(seg)))
        keep: list[int] = []
        used = 0
        for i in dict.fromkeys(idx):
            if used + len(seg[i]) + 1 > PROMPT_CHUNK:  # +1：段间换行也占预算，免得末尾截掉重点段
                if used == 0:  # 单段超长：截断
                    keep.append(i)
                    used = PROMPT_CHUNK
                continue
            keep.append(i)
            used += len(seg[i]) + 1
            if used >= PROMPT_CHUNK:
                break
        chunks.append("\n".join(seg[i] for i in sorted(keep))[:PROMPT_CHUNK])
    return "\n".join(selected), chunks


# ------------------------------------------------------------------ 设定卡规整

def _rel(v: Any) -> list[dict[str, str]]:
    out = []
    for r in v if isinstance(v, list) else []:
        if isinstance(r, dict) and _s(r.get("target"), 20):
            out.append({"target": _s(r.get("target"), 20), "relation": _s(r.get("relation"), 30)})
    return out[:12]


def _norm_char(c: dict[str, Any]) -> dict[str, Any]:
    return {"name": _s(c.get("name"), 20), "aliases": _strs(c.get("aliases"), 6, 20), "role": _s(c.get("role"), 20),
            "personality": _s(c.get("personality"), 160), "speech_style": _s(c.get("speech_style"), 100),
            "catchphrases": _strs(c.get("catchphrases"), 6, 30), "relations": _rel(c.get("relations")),
            "abilities": _strs(c.get("abilities"), 10, 40), "limits": _strs(c.get("limits"), 8, 60), "notes": _s(c.get("notes"), 200)}


def normalize_cards(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    chars = [_norm_char(c) for c in raw.get("characters") or [] if isinstance(c, dict)]
    w = raw.get("world") if isinstance(raw.get("world"), dict) else {}
    world = {"summary": _s(w.get("summary"), 400), "rules": _strs(w.get("rules"), 12, 80),
             "locations": [{"name": _s(x.get("name"), 20), "desc": _s(x.get("desc"), 80)}
                           for x in w.get("locations") or [] if isinstance(x, dict) and _s(x.get("name"), 20)][:20]}
    factions = [{"name": _s(f.get("name"), 30), "stance": _s(f.get("stance"), 60), "members": _strs(f.get("members"), 12, 20),
                 "notes": _s(f.get("notes"), 120)} for f in raw.get("factions") or [] if isinstance(f, dict) and _s(f.get("name"), 30)][:20]
    timeline = []
    for t in raw.get("timeline") or []:
        if isinstance(t, dict) and _s(t.get("event"), 80):
            timeline.append({"order": len(timeline) + 1, "event": _s(t.get("event"), 80), "characters": _strs(t.get("characters"), 8, 20),
                             "impact": _s(t.get("impact"), 60)})
    scenes = [{"title": _s(x.get("title"), 30), "summary": _s(x.get("summary"), 160), "characters": _strs(x.get("characters"), 8, 20)}
              for x in raw.get("scenes") or [] if isinstance(x, dict) and _s(x.get("summary"), 160)][:30]
    return {"characters": [c for c in chars if c["name"]][:MAX_CHARS_CARDS], "world": world, "factions": factions,
            "timeline": timeline[:60], "scenes": scenes}


def merge_parts(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """多轮提炼结果合并：角色按名字/别称合并，时间线与名场面按轮次顺序拼接。"""
    out = normalize_cards({})
    for raw in parts:
        p = normalize_cards(raw)
        for c in p["characters"]:
            keys = {c["name"], *c["aliases"]}
            hit = next((x for x in out["characters"] if keys & {x["name"], *x["aliases"]}), None)
            if hit is None:
                out["characters"].append(c)
                continue
            for k in ("role", "personality", "speech_style", "notes"):
                hit[k] = hit[k] or c[k]
            for k in ("aliases", "catchphrases", "abilities", "limits"):
                hit[k] = list(dict.fromkeys(hit[k] + [x for x in c[k] if x != hit["name"]]))[:10]
            seen = {r["target"] for r in hit["relations"]}
            hit["relations"] += [r for r in c["relations"] if r["target"] not in seen]
        w = p["world"]
        out["world"]["summary"] = out["world"]["summary"] or w["summary"]
        out["world"]["rules"] = list(dict.fromkeys(out["world"]["rules"] + w["rules"]))[:12]
        names = {x["name"] for x in out["world"]["locations"]}
        out["world"]["locations"] += [x for x in w["locations"] if x["name"] not in names]
        for f in p["factions"]:
            hit = next((x for x in out["factions"] if x["name"] == f["name"]), None)
            if hit is None:
                out["factions"].append(f)
            else:
                hit["members"] = list(dict.fromkeys(hit["members"] + f["members"]))[:12]
                hit["stance"] = hit["stance"] or f["stance"]
                hit["notes"] = hit["notes"] or f["notes"]
        out["timeline"] += p["timeline"]
        out["scenes"] += p["scenes"]
    return normalize_cards(out)


def scrub(cards: dict[str, Any], fp: set[int], drop: bool = True) -> tuple[dict[str, Any], list[str]]:
    """和原文有连续 8 字相同的字段：drop=True 时清空字段 / 删掉条目；False（作者手改）只记 warning。口癖、名字不查。"""
    warns: list[str] = []
    if not fp:
        return cards, warns

    def bad(v: Any) -> bool:
        return bool(fp_hits(_leaves(v), fp))

    def hit(where: str) -> None:
        warns.append(f"{where}：和原著有连续 {OVERLAP_N} 字相同，" + ("已清除，请用自己的话写" if drop else "建议改成自己的话"))

    for c in cards["characters"]:
        for k in ("personality", "speech_style", "notes"):
            if c[k] and bad(c[k]):
                hit(f"角色「{c['name']}」·{k}")
                if drop:
                    c[k] = ""
        for k in ("abilities", "limits"):
            keep = []
            for x in c[k]:
                if bad(x):
                    hit(f"角色「{c['name']}」·{k}")
                    if drop:
                        continue
                keep.append(x)
            c[k] = keep
    w = cards["world"]
    if w["summary"] and bad(w["summary"]):
        hit("世界观概述")
        if drop:
            w["summary"] = ""
    for key, label, fields in (("timeline", "时间线", ("event", "impact")), ("scenes", "名场面", ("title", "summary")),
                               ("factions", "势力", ("stance", "notes"))):
        keep = []
        for it in cards[key]:
            if bad({f: it.get(f) for f in fields}):
                hit(f"{label}「{(it.get('title') or it.get('event') or it.get('name') or '')[:12]}」")
                if drop:
                    continue
            keep.append(it)
        cards[key] = keep
    rules = []
    for r in w["rules"]:
        if bad(r):
            hit("世界规则")
            if drop:
                continue
        rules.append(r)
    w["rules"] = rules
    for i, t in enumerate(cards["timeline"], 1):
        t["order"] = i
    return cards, warns


def completeness(cards: dict[str, Any] | None) -> int:
    c = cards or {}
    chars = c.get("characters") or []
    full = [x for x in chars if x.get("personality") and x.get("speech_style")]
    w = c.get("world") or {}
    score = min(30, len(chars) * 10) + (20 * len(full) // max(1, len(chars)) if chars else 0)
    score += 15 if w.get("summary") else 0
    score += 10 if c.get("factions") else 0
    score += min(15, len(c.get("timeline") or []) * 5)
    score += 10 if c.get("scenes") else 0
    return min(100, score)


# ------------------------------------------------------------------ 输出

def _used_by(s: Session, source_id: int) -> list[int]:
    out = []
    for b in s.exec(select(Book)):
        ff = b.fanfic or {}
        if ff.get("source_id") == source_id or source_id in (ff.get("extra_source_ids") or []):
            out.append(int(b.id or 0))
    return out


def source_brief(s: Session, r: FanficSource) -> dict[str, Any]:
    c = r.cards or {}
    return {"id": r.id, "title": r.title, "source": r.source, "chars": r.chars, "total_chars": r.total_chars, "depth": r.depth,
            "focus": list(r.focus or []), "completeness": completeness(c),
            "counts": {k: len(c.get(k) or []) for k in ("characters", "factions", "timeline", "scenes")},
            "warnings_count": len(r.warnings or []), "used_by": _used_by(s, int(r.id or 0)), "model": r.model,
            "template_id": r.template_id or "", "web_rounds": int(r.web_rounds or 0), "refs_count": len(r.refs or []),
            "intro": r.intro or "", "tags": list(r.tags or []), "entry_counts": _lib().counts(r),
            "created_at": _iso(r.created_at), "updated_at": _iso(r.updated_at)}


def _lib():  # noqa: ANN202
    from app.services import fanfic_library

    return fanfic_library


def _books_of(s: Session, ids: list[int]) -> list[dict[str, Any]]:
    out = []
    for i in ids:
        b = s.get(Book, i)
        if b is not None:
            out.append({"id": b.id, "title": b.title, "direction": str((b.fanfic or {}).get("direction") or ""), "words": int(getattr(b, "total_words", 0) or 0)})
    return out


def source_out(s: Session, r: FanficSource) -> dict[str, Any]:
    if _lib().ensure(r):
        s.add(r)
        s.commit()
        s.refresh(r)
    brief = source_brief(s, r)
    return {**brief, "books": _books_of(s, brief["used_by"]), "cards": normalize_cards(r.cards), "warnings": list(r.warnings or []), "refs": list(r.refs or [])}


def _get(s: Session, source_id: int) -> FanficSource:
    r = s.get(FanficSource, source_id)
    if r is None:
        raise NotFound("原著资料不存在")
    return r


def get_source(source_id: int) -> dict[str, Any]:
    with session_scope() as s:
        return source_out(s, _get(s, source_id))


def list_sources() -> list[dict[str, Any]]:
    with session_scope() as s:
        return [source_brief(s, r) for r in s.exec(select(FanficSource).order_by(FanficSource.id.desc()))]  # type: ignore[union-attr]


# ------------------------------------------------------------------ 原著资料：提炼（任务）

def _extract_text(body: str, focus: list[str], depth: str, ctx: JobContext, lo: int, hi: int) -> tuple[str, list[int], list[str], list[dict[str, Any]]]:
    """原文提炼：返回（取用的原文、指纹、猜到的人名、各轮提炼结果）。"""
    ctx.progress(lo, "取材：挑出需要的部分")
    selected, chunks = select_material(body, focus, depth)
    fp_list = fingerprint(selected)
    names = guess_names(selected)
    gw = get_gateway()
    parts: list[dict[str, Any]] = []
    for k, chunk in enumerate(chunks, 1):
        ctx.progress(lo + 5 + int((hi - lo - 5) * (k - 1) / len(chunks)), f"提炼原著设定卡：第 {k}/{len(chunks)} 段")
        meta_lines = [f"程序从原文里猜到的高频人物（仅供参考，可能有误）：{'、'.join(names) or '无'}"]
        if focus:
            meta_lines.append(f"作者想重点整理：{'、'.join(focus)}")
        user = render("fanfic_source", part=k, parts=len(chunks), meta="\n".join(meta_lines), text=chunk,
                      notes=f"本段约 {len(_norm(chunk))} 字。")
        data = gw.chat_json("fanfic_source", system_prompt("fanfic_source"), user, role="reviewer",
                            meta={"names": names, "part": k, "focus": focus})
        if isinstance(data, dict):
            parts.append(data)
    return selected, fp_list, names, parts


def _empty(cards: dict[str, Any]) -> bool:
    return not cards["characters"] and not cards["world"]["summary"] and not cards["timeline"]


def create_source(text: str, source: str, title: str | None, focus: list[str], depth: str, ctx: JobContext,
                  web: bool = False, template_id: str | None = None) -> dict[str, Any]:
    """原著资料：paste/txt 从原文提炼（web=True 时再联网补充，以原文为准）；search 只按作品名联网取材。"""
    from app.services.fanfic_templates import find_template

    check_input(source, text, depth, title, web)
    focus = [f.strip()[:20] for f in focus if f and f.strip()][:10]
    tpl = find_template(template_id, title)
    work = _s(title, 60)
    refs: list[str] = []
    rounds = 0
    if source == "search":
        cards, refs, warns, rounds = gather_web(work, focus, depth, tpl, ctx, 5, 90)
        if _empty(cards):
            raise ValueError(f"联网没有检索到《{work}》足够可靠的设定，请检查作品名，或改用粘贴/上传原文")
        warns.insert(0, f"资料来自联网检索（{rounds} 轮），可能有误或混入同人二设，请逐条核对；不确定的内容没有写入。纯联网资料没有原文指纹，无法做原著重合检查")
        selected, body, fp_list, names = "", "", [], []
    else:
        body = text.strip()
        selected, fp_list, names, parts = _extract_text(body, focus, depth, ctx, 5, 50 if web else 80)
        ctx.progress(52 if web else 85, "合并设定卡、和原文查重")
        cards = merge_parts(parts)
        cards, warns = scrub(cards, set(fp_list), drop=True)
        if web:
            wcards, refs, wwarn, rounds = gather_web(work, focus, depth, tpl, ctx, 55, 88, covered=_covered(cards))
            wcards, swarn = scrub(wcards, set(fp_list), drop=True)
            cards, mwarn, _ = merge_priority(cards, wcards)
            warns += wwarn + swarn + mwarn
        if _empty(cards):
            raise ValueError("没能从原文提炼出设定，请换一段包含人物对话和情节的原文")
        if len(_norm(body)) > len(_norm(selected)):
            warns.insert(0, f"原文约 {len(_norm(body))} 字，按重点/开头/抽样取用了约 {len(_norm(selected))} 字")
    ctx.progress(92, "保存原著资料")
    with session_scope() as s:
        n = len(list(s.exec(select(FanficSource.id)))) + 1
        auto = (names[0] + "相关原著") if names else ""
        row = FanficSource(title=work or auto or f"原著资料 #{n}", source=source, chars=len(_norm(selected)),
                           total_chars=len(_norm(body)), depth=depth, focus=focus, cards=cards, warnings=warns,
                           fingerprint=fp_list, model=_model_name(), refs=refs, template_id=(tpl or {}).get("id", ""),
                           web_rounds=rounds)
        _lib().sync_from_cards(row)
        s.add(row)
        s.commit()
        s.refresh(row)
        return {"source": source_out(s, row), "source_id": row.id}


# ------------------------------------------------------------------ v0.11.1 联网取材 / 联网补充

WEB_ROUNDS = {"quick": 2, "standard": 4, "deep": 6}
MAX_FOCUS_ROUNDS = 6
SEARCH_WORKERS = 3
SEARCH_ANSWER_MAX = 4000  # 每轮检索结果最多取用的字数
NO_SEARCH_MSG = "没有配置联网搜索模型：请到「设置 → 任务路由 → 联网搜索」选一个能联网的模型后再试（也可以改用粘贴/上传原文）"
FANFIC_SEARCH_SYSTEM = (
    "你是同人创作的原著资料整理员，可以联网搜索。用户会给出一部作品名和一个检索主题，请检索百科、设定集、官方介绍、维基等可靠来源，"
    "用中文、用你自己的话整理成可直接用于同人写作的设定资料。\n"
    "要求：\n"
    "1. 只写事实性设定：人物名（保留原著写法和常见别称）、身份定位、性格、说话方式与口头禅、人物关系、能力与上限、"
    "世界规则与力量体系等级、势力立场与成员、关键事件的先后顺序与影响、名场面的简要概括。\n"
    "2. 不要摘抄原著正文或大段台词，口头禅只写短句。\n"
    "3. 区分原著设定与同人二设；小说、动画、游戏、电影等版本有差异时注明版本，默认以原著为准。\n"
    "4. 查不到或说法有争议时直说「不确定」，不要编造。\n"
    "5. 分条列出，600~1200 字为宜；末尾列出 3~6 个来源链接（完整 URL）。"
)
_URL_RE = re.compile(r"https?://[^\s<>\"'）)\]】」』，。、；]+")


def search_mode() -> str:
    """mock：没有任何渠道（演示数据）；web：路由里配了联网搜索模型；none：有渠道但没配搜索。"""
    with session_scope() as s:
        if is_mock_mode(s):
            return "mock"
    return "web" if get_gateway().has_search() else "none"


def require_search() -> None:
    if search_mode() == "none":
        raise FanficError(NO_SEARCH_MSG, 422)


def search_status() -> dict[str, Any]:
    mode = search_mode()
    return {"mode": mode, "available": mode != "none", "hint": NO_SEARCH_MSG if mode == "none" else
            ("演示模式：未联网，返回演示资料" if mode == "mock" else "")}


def plan_queries(work: str, focus: list[str], depth: str, tpl: dict[str, Any] | None = None,
                 supplement: bool = False) -> list[tuple[str, str]]:
    """按深度列检索轮次：quick 2 / standard 4 / deep 6（有模板再加 1）；focus 每项各一轮（最多 6）。"""
    hints = list((tpl or {}).get("search_focus") or [])
    chars = list((tpl or {}).get("characters") or [])
    names = f"《{work}》"
    base = [
        ("概况与世界观", f"{names}作品概况、世界观设定、力量体系与等级划分" + (f"（重点：{'；'.join(hints[:2])}）" if hints else "")),
        ("主要人物", f"{names}主要人物的身份、性格、说话方式、口头禅、人物关系、能力与上限" + (f"，包括{'、'.join(chars[:8])}" if chars else "")),
        ("时间线与名场面", f"{names}主线剧情的关键事件（按先后顺序）与经典名场面"),
        ("势力与地点", f"{names}主要势力/组织的立场与成员，以及重要地点"),
        ("力量体系细节", f"{names}" + ("；".join(hints[2:4]) if len(hints) > 2 else "力量体系的等级细节、能力限制与代价")),
        ("后续剧情与结局", f"{names}中后期剧情走向、结局与续作关系"),
        ("配角与反派", f"{names}重要配角与反派的性格、关系、能力与结局"),
    ]
    n = WEB_ROUNDS.get(depth, 4) + (1 if depth == "deep" and tpl else 0)
    rounds = base[:n]
    if supplement and not any(lbl == "后续剧情与结局" for lbl, _ in rounds):
        rounds.append(base[5])
    if depth == "deep" and len(hints) > 4:
        rounds.append(("设定细节", f"{names}" + "；".join(hints[4:6])))
    for f in focus[:MAX_FOCUS_ROUNDS]:
        rounds.append((f"重点·{f}", f"{names}中「{f}」的资料：如果是人物，写身份、性格、说话方式、口头禅、关系、能力与上限、关键经历；"
                                    f"如果是一段剧情或范围，写经过、出场人物与影响"))
    return rounds


def _mock_search(work: str, label: str, tpl: dict[str, Any] | None, focus: list[str]) -> str:
    names = [*focus, *((tpl or {}).get("characters") or [])][:4] or [f"{work}主角"]
    tid = (tpl or {}).get("id") or "work"
    lines = [f"（演示数据：mock 模式没有联网）《{work}》· {label}",
             f"- {names[0]}是故事的核心人物，经历从弱到强的成长。",
             *[f"- {n}与{names[0]}关系密切，在主线里多次登场。" for n in names[1:]],
             "- 世界存在明确的力量等级，越级挑战需要付出代价。",
             f"来源：https://example.com/novelos-demo/{tid}/{zlib.crc32(label.encode()) % 1000}"]
    return "\n".join(lines)


def _covered(cards: dict[str, Any]) -> str:
    """给检索的写作背景：原文已经覆盖了哪些人物与剧情，让搜索侧重补没覆盖的部分。"""
    names = [c["name"] for c in cards.get("characters") or []][:12]
    tl = [t["event"] for t in cards.get("timeline") or []]
    bits = []
    if names:
        bits.append("作者上传的原文已覆盖这些人物：" + "、".join(names))
    if tl:
        bits.append("原文剧情大致到：" + tl[-1][:40])
    if bits:
        bits.append("请侧重补充原文没有覆盖的人物、设定和后续剧情")
    return "；".join(bits)


def gather_web(work: str, focus: list[str], depth: str, tpl: dict[str, Any] | None, ctx: JobContext, lo: int, hi: int,
               covered: str = "", supplement: bool = False) -> tuple[dict[str, Any], list[str], list[str], int]:
    """多轮联网检索 → 交给 fanfic_source 提炼 → merge_parts。返回（设定卡、来源链接、warnings、成功检索轮数）。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    mode = search_mode()
    if mode == "none":
        raise FanficError(NO_SEARCH_MSG, 422)
    rounds = plan_queries(work, focus, depth, tpl, supplement=supplement or bool(covered))
    gw = get_gateway()
    warns: list[str] = []
    results: dict[int, tuple[str, str]] = {}
    mid = lo + int((hi - lo) * 0.6)
    ctx.progress(lo, f"联网检索《{work}》：共 {len(rounds)} 轮" + ("（演示）" if mode == "mock" else ""))

    def one(i: int) -> tuple[int, str]:
        label, q = rounds[i]
        if mode == "mock":
            return i, _mock_search(work, label, tpl, focus)
        return i, (gw.search(q, covered, system=FANFIC_SEARCH_SYSTEM) or "")

    done = 0
    with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as ex:
        futs = {ex.submit(one, i): i for i in range(len(rounds))}
        for fut in as_completed(futs):
            i = futs[fut]
            done += 1
            try:
                _, ans = fut.result()
                if ans.strip():
                    results[i] = (rounds[i][0], ans.strip()[:SEARCH_ANSWER_MAX])
                else:
                    warns.append(f"联网检索「{rounds[i][0]}」没有返回结果")
            except Exception as e:  # noqa: BLE001
                warns.append(f"联网检索「{rounds[i][0]}」失败：{str(e)[:80]}")
            ctx.progress(lo + int((mid - lo) * done / len(rounds)), f"联网检索：{done}/{len(rounds)} 轮（{rounds[i][0]}）")
    if not results:
        raise ValueError("联网检索全部失败：" + "；".join(warns[-3:]))
    refs: list[str] = []
    for i in sorted(results):
        for u in _URL_RE.findall(results[i][1]):
            u = u.rstrip(".,;:!?")
            if u not in refs:
                refs.append(u)
    blocks = [f"【检索主题：{label}】\n{text}" for label, text in (results[i] for i in sorted(results))]
    chunks: list[str] = []
    cur = ""
    for b in blocks:
        if cur and len(cur) + len(b) + 2 > PROMPT_CHUNK:
            chunks.append(cur)
            cur = ""
        cur = (cur + "\n\n" + b).strip() if cur else b[:PROMPT_CHUNK]
    if cur:
        chunks.append(cur)
    material = "\n".join(blocks)
    names = list(dict.fromkeys([*focus, *((tpl or {}).get("characters") or []), *guess_names(material)]))[:12]
    parts: list[dict[str, Any]] = []
    for k, chunk in enumerate(chunks, 1):
        ctx.progress(mid + int((hi - mid) * (k - 1) / len(chunks)), f"整理联网资料：第 {k}/{len(chunks)} 段")
        meta_lines = [f"作品：《{work}》"]
        if names:
            meta_lines.append(f"可能的主要人物（仅供参考）：{'、'.join(names)}")
        if focus:
            meta_lines.append(f"作者想重点整理：{'、'.join(focus)}")
        if covered:
            meta_lines.append(covered)
        user = render("fanfic_source_web", work=work, part=k, parts=len(chunks), meta="\n".join(meta_lines), text=chunk,
                      notes="材料来自联网检索，可能有误；不确定的不写。")
        data = get_gateway().chat_json("fanfic_source", system_prompt("fanfic_source"), user, role="reviewer",
                                       meta={"names": names, "part": k, "focus": focus, "web": True})
        if isinstance(data, dict):
            parts.append(data)
    return merge_parts(parts), refs[:30], warns, len(results)


def _diff(a: str, b: str) -> bool:
    """两个短字段明显不一致（都非空、互不包含）。"""
    a, b = _norm(a), _norm(b)
    return bool(a and b and a not in b and b not in a)


def merge_priority(base: dict[str, Any], extra: dict[str, Any]) -> tuple[dict[str, Any], list[str], dict[str, int]]:
    """以 base（原文提炼 / 已有资料）为准合并 extra（联网结果）：只补空字段和缺的条目，冲突以 base 为准并记 warning。"""
    out = normalize_cards(base)
    ex = normalize_cards(extra)
    warns: list[str] = []
    added = {"characters": 0, "factions": 0, "timeline": 0, "scenes": 0, "rules": 0, "locations": 0}
    for c in ex["characters"]:
        keys = {c["name"], *c["aliases"]}
        hit = next((x for x in out["characters"] if keys & {x["name"], *x["aliases"]}), None)
        if hit is None:
            if len(out["characters"]) >= MAX_CHARS_CARDS:
                continue
            c["notes"] = ("（联网补充，可能有误，请核对）" + c["notes"])[:200]
            out["characters"].append(c)
            added["characters"] += 1
            continue
        if _diff(hit["role"], c["role"]):
            warns.append(f"联网资料与原文不一致：角色「{hit['name']}」定位（原文：{hit['role']}；联网：{c['role']}），已以原文为准")
        for k in ("role", "personality", "speech_style", "notes"):
            hit[k] = hit[k] or c[k]
        for k in ("aliases", "abilities", "limits"):
            hit[k] = list(dict.fromkeys(hit[k] + [x for x in c[k] if x != hit["name"]]))[:10]
        hit["catchphrases"] = hit["catchphrases"] or c["catchphrases"]
        mine = {r["target"]: r["relation"] for r in hit["relations"]}
        for r in c["relations"]:
            if r["target"] not in mine:
                hit["relations"].append(r)
            elif _diff(mine[r["target"]], r["relation"]):
                warns.append(f"联网资料与原文不一致：「{hit['name']}」与「{r['target']}」的关系（原文：{mine[r['target']]}；联网：{r['relation']}），已以原文为准")
        hit["relations"] = hit["relations"][:12]
    w, xw = out["world"], ex["world"]
    w["summary"] = w["summary"] or xw["summary"]
    for r in xw["rules"]:
        if r not in w["rules"] and len(w["rules"]) < 12:
            w["rules"].append(r)
            added["rules"] += 1
    have = {x["name"] for x in w["locations"]}
    for x in xw["locations"]:
        if x["name"] not in have and len(w["locations"]) < 20:
            w["locations"].append(x)
            added["locations"] += 1
    for f in ex["factions"]:
        hit = next((x for x in out["factions"] if x["name"] == f["name"]), None)
        if hit is None:
            out["factions"].append(f)
            added["factions"] += 1
            continue
        if _diff(hit["stance"], f["stance"]):
            warns.append(f"联网资料与原文不一致：势力「{hit['name']}」立场（原文：{hit['stance']}；联网：{f['stance']}），已以原文为准")
        hit["stance"] = hit["stance"] or f["stance"]
        hit["notes"] = hit["notes"] or f["notes"]
        hit["members"] = list(dict.fromkeys(hit["members"] + f["members"]))[:12]
    seen_ev = {_norm(t["event"]) for t in out["timeline"]}
    for t in ex["timeline"]:
        if _norm(t["event"]) not in seen_ev:
            seen_ev.add(_norm(t["event"]))
            out["timeline"].append(t)
            added["timeline"] += 1
    seen_sc = {_norm(x["title"]) for x in out["scenes"]} | {_norm(x["summary"]) for x in out["scenes"]}
    for x in ex["scenes"]:
        if _norm(x["title"]) not in seen_sc and _norm(x["summary"]) not in seen_sc:
            out["scenes"].append(x)
            added["scenes"] += 1
    cards = normalize_cards(out)
    total = sum(added.values())
    if total:
        warns.insert(0, "联网补充：" + "、".join(f"{lbl} {added[k]}" for k, lbl in (("characters", "角色"), ("factions", "势力"),
                     ("timeline", "时间线"), ("scenes", "名场面"), ("rules", "世界规则"), ("locations", "地点")) if added[k])
                     + "（以原文为准，联网内容可能有误，请核对）")
    else:
        warns.insert(0, "联网补充：没有发现原文之外的新内容")
    return cards, warns, added


def check_supplement(source_id: int) -> None:
    with session_scope() as s:
        _get(s, source_id)
    require_search()


def supplement_source(source_id: int, focus: list[str] | None, depth: str, ctx: JobContext) -> dict[str, Any]:
    """给已有的原著资料联网补充（后台 Job）：以已有设定卡为准，只补空缺，冲突记 warning。"""
    from app.services.fanfic_templates import find_template

    if depth not in DEPTHS:
        raise FanficError("depth 只能是 quick / standard / deep", 422)
    with session_scope() as s:
        r = _get(s, source_id)
        work, tid = r.title, r.template_id
        base = normalize_cards(r.cards)
        fp = set(r.fingerprint or [])
        fc = [f.strip()[:20] for f in (focus if focus is not None else list(r.focus or [])) if f and f.strip()][:10]
    require_search()
    tpl = find_template(tid, work)
    wcards, refs, wwarn, rounds = gather_web(work, fc, depth, tpl, ctx, 5, 88, covered=_covered(base), supplement=True)
    wcards, swarn = scrub(wcards, fp, drop=True)
    cards, mwarn, added = merge_priority(base, wcards)
    new_warns = wwarn + swarn + mwarn
    ctx.progress(92, "保存补充结果")
    with session_scope() as s:
        r = _get(s, source_id)
        r.cards = cards
        r.warnings = list(dict.fromkeys(list(r.warnings or []) + new_warns))[-50:]
        r.refs = list(dict.fromkeys(list(r.refs or []) + refs))[:50]
        r.web_rounds = int(r.web_rounds or 0) + rounds
        r.template_id = r.template_id or (tpl or {}).get("id", "")
        _lib().sync_from_cards(r)
        r.updated_at = datetime.now(timezone.utc)
        s.add(r)
        s.commit()
        s.refresh(r)
        return {"source": source_out(s, r), "source_id": r.id, "added": added, "warnings": new_warns}


def _model_name() -> str:
    from app.llm.gateway import resolve_targets

    with session_scope() as s:
        ts = resolve_targets(s, "reviewer")
    return f"{ts[0].name}/{ts[0].model}" if ts else "mock"


def update_source(source_id: int, title: str | None, cards: dict[str, Any] | None) -> dict[str, Any]:
    """作者手改设定卡：cards 里给了哪几块就整块替换哪几块；和原著重合的只提醒不删。"""
    with session_scope() as s:
        r = _get(s, source_id)
        warns: list[str] = []
        if title is not None and title.strip():
            r.title = title.strip()[:60]
        if cards is not None:
            bad = [k for k in cards if k not in CARD_PARTS]
            if bad:
                raise FanficError(f"cards 只能包含 {'/'.join(CARD_PARTS)}", 422)
            cur = normalize_cards(r.cards)
            new = normalize_cards({**cur, **cards})
            new, warns = scrub(new, set(r.fingerprint or []), drop=False)
            r.cards = new
        r.updated_at = datetime.now(timezone.utc)
        s.add(r)
        s.commit()
        s.refresh(r)
        return {"source": source_out(s, r), "warnings": warns}


def delete_source(source_id: int, force: bool = False) -> None:
    with session_scope() as s:
        r = _get(s, source_id)
        used = _used_by(s, source_id)
        if used and not force:
            raise Conflict(f"有 {len(used)} 本同人书在用这份原著资料（书 {', '.join(map(str, used))}），确认删除请加 ?force=true")
        s.delete(r)
        s.commit()


# ------------------------------------------------------------------ 同人书

def validate_spec(s: Session, spec: dict[str, Any], ack: bool) -> dict[str, Any]:
    if ack is not True:
        raise FanficError("创建同人书前请先阅读并确认版权声明（copyright_ack: true）")
    fidelity = spec.get("fidelity") or "moderate"
    direction = spec.get("direction") or "canon_fill"
    if fidelity not in FIDELITIES:
        raise FanficError("fidelity 只能是 strict / moderate / loose", 422)
    if direction not in DIRECTION_IDS:
        raise FanficError(f"direction 只能是 {'/'.join(DIRECTION_IDS)}", 422)
    try:
        sid = int(spec.get("source_id"))  # type: ignore[arg-type]
    except (TypeError, ValueError) as e:
        raise FanficError("缺少 source_id", 422) from e
    src = _get(s, sid)
    extra = [int(x) for x in dict.fromkeys(spec.get("extra_source_ids") or []) if int(x) != sid][:9]
    for x in extra:
        _get(s, x)
    out = {"source_id": sid, "source_title": src.title, "fidelity": fidelity, "direction": direction,
           "extra_source_ids": extra, "notes": _s(spec.get("notes"), 1000)}
    p = spec.get("protagonist")
    if isinstance(p, dict):  # v0.13 原创主角 / 原著角色当主角
        src_kind = "oc" if p.get("source") == "oc" else "canon"
        prot = {"source": src_kind, "name": _s(p.get("name"), 20), "brief": _s(p.get("brief"), 500),
                "entry_event": _s(p.get("entry_event"), 120)}
        if src_kind == "oc":
            prot["oc_type"] = p.get("oc_type") if p.get("oc_type") in OC_TYPES else "transmigrator"
            if prot["oc_type"] == "soul_swap":
                prot["canon_name"] = _s(p.get("canon_name"), 20)
        else:
            prot["canon_name"] = _s(p.get("canon_name") or p.get("name"), 20)
        out["protagonist"] = prot
    if spec.get("pov") in POVS:
        out["pov"] = spec["pov"]
    if isinstance(spec.get("slots"), dict):
        out["slots"] = {str(k)[:10]: _s(v, 200) for k, v in list(spec["slots"].items())[:8] if _s(v, 200)}
    return out


def attach(s: Session, book: Book, spec: dict[str, Any], ack: bool) -> dict[str, Any]:
    ff = validate_spec(s, spec, ack)
    now = _now()
    old = book.fanfic or {}
    book.fanfic = {**ff, "copyright_ack": True, "copyright_ack_at": now, "attached_at": old.get("attached_at") or now}
    book.updated_at = datetime.now(timezone.utc)
    s.add(book)
    s.commit()
    s.refresh(book)
    return fanfic_out(s, book)


def patch(s: Session, book: Book, changes: dict[str, Any]) -> dict[str, Any]:
    if not book.fanfic:
        raise FanficError("这本书不是同人书，请先用 POST /books/{id}/fanfic 关联原著并确认版权声明")
    merged = {**book.fanfic, **{k: v for k, v in changes.items() if v is not None}}
    ff = validate_spec(s, merged, True)
    book.fanfic = {**book.fanfic, **ff}
    book.updated_at = datetime.now(timezone.utc)
    s.add(book)
    s.commit()
    s.refresh(book)
    return fanfic_out(s, book)


def detach(s: Session, book: Book) -> None:
    book.fanfic = None
    s.add(book)
    s.commit()


def fanfic_out(s: Session, book: Book) -> dict[str, Any]:
    ff = book.fanfic
    if not ff:
        return {"book_id": book.id, "fanfic": None}
    src = s.get(FanficSource, int(ff.get("source_id") or 0))
    d = DIRECTION_BY_ID.get(str(ff.get("direction")), {})
    fid = FIDELITY.get(str(ff.get("fidelity")), {})
    return {"book_id": book.id, "fanfic": {**ff, "direction_label": d.get("label", ""), "fidelity_label": fid.get("label", ""),
                                           "source": source_brief(s, src) if src else None, "source_missing": src is None}}


def import_cards(book_id: int, parts: list[str]) -> dict[str, Any]:
    """把原著卡写进本书设定库（角色带说话方式/口癖，写章时自动进相关设定）。重名跳过。"""
    from app.api.schemas import card_out
    from app.services import bible_ops, common

    bad = [p for p in parts if p not in IMPORT_PARTS]
    if not parts or bad:
        raise FanficError(f"parts 只能是 {'/'.join(IMPORT_PARTS)}", 422)
    with session_scope() as s:
        book = common.get_book(s, book_id)
        if not book.fanfic:
            raise FanficError("这本书不是同人书")
        src = _get(s, int(book.fanfic.get("source_id") or 0))
        cards = normalize_cards(src.cards)
        tag = {"from_fanfic_source": src.id}
        drafts: list[dict[str, Any]] = []
        if "characters" in parts:
            for c in cards["characters"]:
                role = "protagonist" if "主角" in c["role"] else ("antagonist" if "反派" in c["role"] else "ally")
                drafts.append({"type": "character", "name": c["name"], "summary": c["personality"] or c["role"],
                               "data": {**tag, "role": role, "voice": c["speech_style"], "catchphrases": c["catchphrases"],
                                        "abilities": c["abilities"], "limits": c["limits"], "relations": c["relations"],
                                        "aliases": c["aliases"], "canon_role": c["role"]}})
        if "factions" in parts:
            for f in cards["factions"]:
                drafts.append({"type": "faction", "name": f["name"], "summary": f["stance"] or f["notes"],
                               "data": {**tag, "members": f["members"], "notes": f["notes"]}})
        if "world" in parts and (cards["world"]["summary"] or cards["world"]["rules"]):
            drafts.append({"type": "world", "name": "原著世界观", "summary": cards["world"]["summary"],
                           "data": {**tag, "rules": cards["world"]["rules"]}})
        if "locations" in parts:
            for x in cards["world"]["locations"]:
                drafts.append({"type": "location", "name": x["name"], "summary": x["desc"], "data": dict(tag)})
        if not drafts:
            return {"cards": [], "skipped": 0}
        bible_ops.snapshot(s, book_id, f"导入原著资料#{src.id} 前")
        existing = {c.name for c in common.cards(s, book_id, include_deprecated=True)}
        made: list[Card] = []
        skipped = 0
        for d in drafts:
            if d["name"] in existing:
                skipped += 1
                continue
            existing.add(d["name"])
            c = Card(book_id=book_id, type=d["type"], name=d["name"][:40], summary=d["summary"], data=d["data"], known_by=[])
            s.add(c)
            made.append(c)
        s.commit()
        for c in made:
            s.refresh(c)
        return {"cards": [card_out(c) for c in made], "skipped": skipped}


# ------------------------------------------------------------------ 上下文注入（common.book_context 钩子）

def _char_line(c: dict[str, Any], fidelity: str) -> str:
    bits = [f"{c['name']}" + (f"（{c['role']}）" if c["role"] else "")]
    if c["aliases"]:
        bits.append("又称" + "、".join(c["aliases"][:3]))
    if c["personality"]:
        bits.append("性格：" + c["personality"])
    if c["speech_style"]:
        bits.append("说话：" + c["speech_style"])
    if c["catchphrases"]:
        bits.append("口癖：" + "、".join(f"「{x}」" for x in c["catchphrases"][:3]) + "（点到为止，别刷屏）")
    if fidelity != "loose":
        if c["relations"]:
            bits.append("关系：" + "、".join(f"{r['target']}={r['relation']}" for r in c["relations"][:4]))
        if c["abilities"]:
            bits.append("能力：" + "、".join(c["abilities"][:4]))
        if c["limits"]:
            bits.append("边界：" + "、".join(c["limits"][:3]))
    return "；".join(bits)


def context_block(s: Session, book: Book, budget: int = CONTEXT_BUDGET) -> str:
    """同人书的原著卡摘要 + 遵循规则；原创书返回空串。"""
    ff = getattr(book, "fanfic", None)
    if not ff:
        return ""
    src = s.get(FanficSource, int(ff.get("source_id") or 0))
    fidelity = ff.get("fidelity") if ff.get("fidelity") in FIDELITIES else "moderate"
    rule = FIDELITY[fidelity]
    d = DIRECTION_BY_ID.get(str(ff.get("direction")), {})
    lines = [f"【同人创作·原著设定（{(src.title if src else ff.get('source_title')) or '原著'}；遵循度：{rule['label']}）】",
             "遵循规则：" + rule["rule"]]
    if d:
        lines.append(f"创作方向：{d['label']}——{d['desc']} 要点：{'；'.join(d['tips'])}")
    if ff.get("notes"):
        lines.append("作者补充：" + str(ff["notes"])[:300])
    if d and ff.get("slots"):
        lab = {x["key"]: x["label"] for x in d.get("slots") or []}
        lines.append("作者的想法：" + "；".join(f"{lab.get(k, k)}：{v}" for k, v in ff["slots"].items()))
    if ff.get("pov") in POVS:
        lines.append("视角：" + POVS[ff["pov"]]["rule"])
    prot = ff.get("protagonist") if isinstance(ff.get("protagonist"), dict) else None
    if prot:
        oc = next((c for c in common.cards(s, book.id or 0) if (c.data or {}).get("origin") == "oc"), None)
        if prot.get("source") == "oc":
            kind = OC_TYPES.get(str(prot.get("oc_type")), "原创角色")
            if oc is not None:
                d2 = oc.data or {}
                bits = [f"{lab}：{d2[k]}" for k, lab in (("identity", "身份"), ("ability", "能力"), ("limit", "现阶段上限"), ("growth", "成长路线"),
                                                         ("goal", "目标"), ("voice", "说话方式")) if d2.get(k)]
                lines.append(f"原创主角（{kind}）{oc.name}：{oc.summary}" + ("；" + "；".join(bits) if bits else ""))
            elif prot.get("name") or prot.get("brief"):
                lines.append(f"原创主角（{kind}）{prot.get('name') or ''}：{prot.get('brief') or ''}")
            if prot.get("oc_type") == "soul_swap" and prot.get("canon_name"):
                lines.append(f"魂穿对象：{prot['canon_name']}（外人眼里他还是{prot['canon_name']}，身体身份按原著，内在换了人）")
            lines.append("原创主角的能力与成长不得越过原著力量体系的上限，不得和原著时间线冲突。")
        elif prot.get("canon_name"):
            lines.append(f"主角：原著角色{prot['canon_name']}")
    entry = str((prot or {}).get("entry_event") or "")
    if src is not None and entry:
        tl = normalize_cards(src.cards)["timeline"]
        k = next((i for i, t in enumerate(tl) if entry in t["event"] or t["event"] in entry), None)
        if k is not None:
            near = tl[max(0, k - 3):k + 4]
            lines.append(f"切入时间点：{tl[k]['event']}。前后原著事件：" + " → ".join(t["event"] for t in near))
        else:
            lines.append(f"切入时间点：{entry}")
    lines.append("写作要求：情节、对白全部原创，不要复述或照抄原著句子（与原著连续 8 字相同会被标记）。")
    if src is None:
        lines.append("（原著资料已删除，只按上面的规则把握）")
        return "\n".join(lines)
    cards = normalize_cards(src.cards)
    lines.append("原著角色：")
    lines += [f"- {_char_line(c, fidelity)}" for c in cards["characters"][:10]]
    w = cards["world"]
    if fidelity != "loose" and (w["summary"] or w["rules"]):
        lines.append("原著世界观：" + w["summary"] + ("；规则：" + "；".join(w["rules"][:6]) if w["rules"] else ""))
    if fidelity != "loose" and cards["factions"]:
        lines.append("势力：" + "；".join(f"{f['name']}（{f['stance']}）" for f in cards["factions"][:6]))
    if fidelity == "strict" and cards["timeline"]:
        lines.append("原著时间线（已发生，不得改写）：" + " → ".join(t["event"] for t in cards["timeline"][:12]))
    elif fidelity == "moderate" and cards["timeline"]:
        lines.append("原著主线节点（支线与结局可改）：" + " → ".join(t["event"] for t in cards["timeline"][:8]))
    lines += _lib().context_lines(src, " ".join([str(getattr(book, "premise", "") or ""), str(ff.get("notes") or ""), entry]), fidelity)
    for xid in ff.get("extra_source_ids") or []:
        x = s.get(FanficSource, int(xid))
        if x is not None:
            xc = normalize_cards(x.cards)
            lines.append(f"联动原著「{x.title}」角色：" + "；".join(_char_line(c, "loose") for c in xc["characters"][:5]))
    text = "\n".join(lines)
    return text if len(text) <= budget else text[:budget] + "…"


# ------------------------------------------------------------------ 原著重合（融合二创检查）

def _norm_map(text: str) -> tuple[str, list[int]]:
    """去空白和标点后的文本，及每个字在原文里的下标（与 imitate._norm 规则一致）。"""
    chars, idx = [], []
    for i, ch in enumerate(text or ""):
        if _norm(ch):
            chars.append(ch)
            idx.append(i)
    return "".join(chars), idx


def _exclude_grams(cards: dict[str, Any]) -> set[int]:
    """口癖、角色名这类同人必然沿用的说法，不计入重合。"""
    ex: set[int] = set()
    for c in cards.get("characters") or []:
        for x in list(c.get("catchphrases") or []) + [c.get("name") or ""] + list(c.get("aliases") or []):
            ex.update(fingerprint(str(x)))
    return ex


def overlap_stats(text: str, fp: set[int], exclude: set[int] | None = None, n: int = OVERLAP_N) -> dict[str, Any]:
    ex = exclude or set()
    t, idx = _norm_map(text)
    total = max(0, len(t) - n + 1)
    runs: list[tuple[int, int]] = []
    hits = 0
    start = last = -2
    for i in range(total):
        h = zlib.crc32(t[i:i + n].encode("utf-8"))
        if h not in fp or h in ex:
            continue
        hits += 1
        if i == last + 1:
            last = i
            continue
        if start >= 0:
            runs.append((start, last))
        start = last = i
    if start >= 0:
        runs.append((start, last))
    longest = max(((b - a) + n for a, b in runs), default=0)
    ratio = round(hits / total, 4) if total else 0.0
    if not runs:
        level, warn = "ok", ""
    elif ratio < 0.01 and longest < 20:
        level, warn = "info", f"有 {len(runs)} 处与原著连续 {n} 字相同，多为称谓或常用短语，可酌情保留"
    elif ratio < 0.05:
        level, warn = "warn", f"有 {len(runs)} 处与原著连续 {n} 字以上相同（最长 {longest} 字），建议改成自己的表达"
    else:
        level, warn = "high", f"与原著重合偏高：{len(runs)} 处、约 {ratio:.0%} 的 8 字片段相同，发布前务必改写"
    samples = []
    for a, b in sorted(runs, key=lambda r: r[0] - r[1])[:5]:
        lo, hi = idx[a], idx[min(len(idx) - 1, b + n - 1)]
        samples.append((text[lo:hi + 1])[:60])
    return {"ngram": n, "hits": hits, "segments": len(runs), "longest": longest, "ratio": ratio, "level": level,
            "warning": warn, "samples": samples}


def _overlap(text: str, fp: set[int], ex: set[int]) -> dict[str, Any]:
    """v0.11.1：纯联网资料没有原文指纹，重合检查标 no_fingerprint 并说明，不报错。"""
    res = overlap_stats(text, fp, ex)
    if not fp:
        res["no_fingerprint"] = True
        res["warning"] = "这份原著资料来自联网检索，没有原文指纹，无法做原著重合检查；如有原文可上传原著并联网补充"
    return res


def _book_source(s: Session, book_id: int) -> tuple[Book, FanficSource | None]:
    from app.services import common

    book = common.get_book(s, book_id)
    if not book.fanfic:
        raise FanficError("这本书不是同人书")
    return book, s.get(FanficSource, int(book.fanfic.get("source_id") or 0))


def _fp_all(s: Session, book: Book, src: FanficSource | None) -> tuple[set[int], set[int]]:
    fp = set(src.fingerprint or []) if src else set()
    ex = _exclude_grams(src.cards or {}) if src else set()
    for xid in (book.fanfic or {}).get("extra_source_ids") or []:
        x = s.get(FanficSource, int(xid))
        if x is not None:
            fp |= set(x.fingerprint or [])
            ex |= _exclude_grams(x.cards or {})
    return fp, ex


def chapter_overlap(chapter_id: int, save: bool = True) -> dict[str, Any]:
    from app.services.zhuque import content_hash

    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        book, src = _book_source(s, ch.book_id)
        if src is None:
            raise FanficError("原著资料已删除，无法比对")
        fp, ex = _fp_all(s, book, src)
        res = {**_overlap(ch.content or "", fp, ex), "content_hash": content_hash(ch.content or ""), "checked_at": _now()}
        if save:
            ch.fanfic_meta = {**(ch.fanfic_meta or {}), "overlap": res}
            s.add(ch)
            s.commit()
        return {"chapter_id": chapter_id, "overlap": res}


def text_overlap(book_id: int, text: str) -> dict[str, Any]:
    """给写章/改写用：任意一段文字与本书原著的重合统计（原创书返回 level=ok）。"""
    with session_scope() as s:
        book = s.get(Book, book_id)
        if book is None or not book.fanfic:
            return overlap_stats("", set())
        src = s.get(FanficSource, int(book.fanfic.get("source_id") or 0))
        fp, ex = _fp_all(s, book, src)
        return overlap_stats(text, fp, ex)


# ------------------------------------------------------------------ OOC 检查

def _present(cards: dict[str, Any], content: str) -> list[dict[str, Any]]:
    return [c for c in cards.get("characters") or [] if any(k and k in content for k in [c["name"], *c["aliases"]])]


def _first_quote(content: str, c: dict[str, Any]) -> str:
    for m in _SENT_RE.finditer(content):
        sent = m.group(0).strip()
        if len(sent) >= 6 and any(k and k in sent for k in [c["name"], *c["aliases"]]):
            return sent[:60]
    return ""


def _char_card_text(c: dict[str, Any]) -> str:
    return _char_line(c, "strict")


def check_ooc(chapter_id: int) -> int:
    """同步预检：返回 book_id；不是同人书 / 没正文 / 原著已删 → 400。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        _, src = _book_source(s, ch.book_id)
        if src is None:
            raise FanficError("原著资料已删除，无法做 OOC 检查")
        if not (ch.content or "").strip():
            raise FanficError("这一章还没有正文")
        return ch.book_id


def _catchphrase_issues(present: list[dict[str, Any]], content: str) -> list[dict[str, Any]]:
    out = []
    for c in present:
        for cp in c["catchphrases"]:
            if len(cp) >= 2 and content.count(cp) > CATCHPHRASE_MAX:
                out.append({"name": c["name"], "type": "catchphrase", "type_label": OOC_TYPES["catchphrase"], "severity": "low",
                            "quote": cp, "problem": f"口癖「{cp}」本章出现 {content.count(cp)} 次，刷屏",
                            "suggestion": f"保留 1–2 次，其余用{c['name']}的说话方式体现", "source": "program"})
    return out


def run_ooc(chapter_id: int, ctx: JobContext) -> dict[str, Any]:
    from app.services.review import quote_in_text
    from app.services.zhuque import content_hash

    check_ooc(chapter_id)
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        book, src = _book_source(s, ch.book_id)
        assert src is not None
        ff = dict(book.fanfic or {})
        _bid = ch.book_id
        content = ch.content or ""
        cards = normalize_cards(src.cards)
        fp, ex = _fp_all(s, book, src)
    fidelity = ff.get("fidelity") if ff.get("fidelity") in FIDELITIES else "moderate"
    rule = FIDELITY[fidelity]
    d = DIRECTION_BY_ID.get(str(ff.get("direction")), {})
    present = _present(cards, content)
    with session_scope() as s:  # v0.13 原创主角：只查世界规则（能力越过原著上限、和时间线冲突）
        oc = next((c for c in common.cards(s, _bid) if (c.data or {}).get("origin") == "oc"), None)
        if oc is not None and oc.name in content:
            od = oc.data or {}
            present.append(_norm_char({"name": oc.name, "role": "原创主角", "personality": od.get("personality") or oc.summary,
                                       "speech_style": od.get("voice") or "", "abilities": [str(od.get("ability") or "")],
                                       "limits": [str(od.get("limit") or "")], "notes": f"原创角色，只检查世界规则：成长路线 {od.get('growth') or ''}"}))
    ctx.progress(15, f"对照原著角色卡：本章出场 {len(present)} 人")
    raw: dict[str, Any] = {}
    if present:
        w = cards["world"]
        user = render("fanfic_ooc", fidelity_label=rule["label"], fidelity_rule=rule["rule"],
                      direction=f"{d.get('label', '')}：{d.get('desc', '')}" if d else "未指定",
                      characters="\n".join(f"- {_char_card_text(c)}" for c in present[:8]),
                      world=(w["summary"] + "；" + "；".join(w["rules"][:6])) if fidelity != "loose" else "（AU：不按原著世界观检查）",
                      content=content[:OOC_CONTENT])
        got = get_gateway().chat_json("fanfic_ooc", system_prompt("fanfic_ooc"), user, role="reviewer",
                                      meta={"characters": [c["name"] for c in present[:8]],
                                            "quotes": {c["name"]: _first_quote(content, c) for c in present[:8]}})
        raw = got if isinstance(got, dict) else {}
    ctx.progress(80, "按遵循度调整宽严、查原著重合")
    by_name = {c["name"]: c for c in present}
    rows: dict[str, dict[str, Any]] = {}
    ignored = 0
    for it in raw.get("characters") or []:
        if not isinstance(it, dict):
            continue
        name = _s(it.get("name"), 20)
        c = by_name.get(name) or next((x for x in present if name in x["aliases"]), None)
        if c is None:
            continue
        issues = []
        for x in it.get("issues") or []:
            if not isinstance(x, dict):
                continue
            typ = str(x.get("type") or "speech").lower()
            typ = typ if typ in OOC_TYPES else "speech"
            sev = str(x.get("severity") or "low").lower()
            sev = sev if sev in PENALTY else "low"
            quote = _s(x.get("quote"), 120)
            if not quote_in_text(quote, content):
                continue
            if typ in rule["ignore"]:
                ignored += 1
                continue
            if fidelity == "strict" and typ in ("relation", "ability", "timeline") and sev == "low":
                sev = "mid"
            if fidelity == "loose" and sev == "high" and typ != "speech":
                sev = "mid"
            issues.append({"type": typ, "type_label": OOC_TYPES[typ], "severity": sev, "quote": quote,
                           "problem": _s(x.get("problem"), 120), "suggestion": _s(x.get("suggestion"), 120), "source": "model"})
        try:
            mscore = max(0, min(100, int(round(float(it.get("score"))))))
        except (TypeError, ValueError):
            mscore = 80
        rows[c["name"]] = {"name": c["name"], "model_score": mscore, "verdict": _s(it.get("verdict"), 80), "issues": issues}
    for c in present:
        rows.setdefault(c["name"], {"name": c["name"], "model_score": None, "verdict": "", "issues": []})
    for x in _catchphrase_issues(present, content):
        rows[x.pop("name")]["issues"].append(x)
    pass_score = int(rule["pass"])
    chars_out = []
    for r in rows.values():
        computed = max(0, 100 - int(sum(PENALTY[i["severity"]] for i in r["issues"]) * float(rule["factor"])))
        score = computed if r["model_score"] is None else round((r["model_score"] + computed) / 2)
        high = any(i["severity"] == "high" for i in r["issues"])
        level = "pass" if score >= pass_score and not high else ("warn" if score >= pass_score - 15 else "fail")
        chars_out.append({**r, "score": score, "level": level})
    overall = round(sum(x["score"] for x in chars_out) / len(chars_out)) if chars_out else 100
    verdict = "fail" if any(x["level"] == "fail" for x in chars_out) else ("warn" if any(x["level"] == "warn" for x in chars_out) else "pass")
    h = content_hash(content)
    result = {"fidelity": fidelity, "fidelity_label": rule["label"], "pass_score": pass_score, "overall": overall, "verdict": verdict,
              "characters": chars_out, "summary": _s(raw.get("summary"), 300) or ("本章没有出场原著角色" if not present else ""),
              "ignored_issues": ignored, "content_hash": h, "checked_at": _now(), "model": _model_name()}
    overlap = {**_overlap(content, fp, ex), "content_hash": h, "checked_at": _now()}
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is not None:
            ch.fanfic_meta = {**(ch.fanfic_meta or {}), "ooc": result, "overlap": overlap}
            s.add(ch)
            s.commit()
    return {"chapter_id": chapter_id, "ooc": result, "overlap": overlap}


def chapter_fanfic_meta(chapter_id: int) -> dict[str, Any]:
    from app.services.zhuque import content_hash

    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        meta = dict(ch.fanfic_meta or {})
        h = content_hash(ch.content or "")
        out: dict[str, Any] = {"chapter_id": chapter_id}
        for k in ("ooc", "overlap"):
            v = meta.get(k)
            out[k] = {**v, "stale": v.get("content_hash") != h} if isinstance(v, dict) else None
        return out


def ooc_block(s: Session, chapter: Chapter, content: str | None = None) -> list[dict[str, Any]]:
    """给审稿用（确定性，不调模型）：返回审稿格式的 issues [{severity, dimension:"character", quote, comment}]。

    - 已存的 OOC 结果（正文没变时）里的每条问题；
    - 口癖刷屏；
    - 与原著重合 level=warn/high 时一条（quote 取本章里重合最长的那段）。
    原创书、原著已删时返回 []。
    """
    from app.services.review import quote_in_text
    from app.services.zhuque import content_hash

    book = s.get(Book, chapter.book_id)
    if book is None or not book.fanfic:
        return []
    src = s.get(FanficSource, int(book.fanfic.get("source_id") or 0))
    if src is None:
        return []
    text = chapter.content if content is None else content
    text = text or ""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    ooc = (chapter.fanfic_meta or {}).get("ooc")
    if isinstance(ooc, dict) and ooc.get("content_hash") == content_hash(text):
        for c in ooc.get("characters") or []:
            for i in c.get("issues") or []:
                q = str(i.get("quote") or "")
                if quote_in_text(q, text) and q not in seen:
                    seen.add(q)
                    out.append({"severity": i.get("severity", "low"), "dimension": "character", "quote": q,
                                "comment": f"[OOC·{c.get('name')}·{i.get('type_label', '')}] {i.get('problem', '')}；建议：{i.get('suggestion', '')}"[:300]})
    cards = normalize_cards(src.cards)
    for i in _catchphrase_issues(_present(cards, text), text):
        if i["quote"] not in seen and quote_in_text(i["quote"], text, min_len=2):
            out.append({"severity": "low", "dimension": "character", "quote": i["quote"], "comment": f"[OOC·口癖] {i['problem']}；建议：{i['suggestion']}"})
    fp, ex = _fp_all(s, book, src)
    ov = overlap_stats(text, fp, ex)
    if ov["level"] in ("warn", "high") and ov["samples"]:
        out.append({"severity": "high" if ov["level"] == "high" else "mid", "dimension": "semantics", "quote": ov["samples"][0],
                    "comment": f"[原著重合] {ov['warning']}"})
    return out


# ------------------------------------------------------------------ v0.13 原创主角

def generate_oc(book_id: int, ctx: JobContext) -> dict[str, Any]:
    from app.models.tables import Card
    from app.services import bible_ops

    with session_scope() as s:
        book, src = _book_source(s, book_id)
        ff = dict(book.fanfic or {})
        prot = ff.get("protagonist") if isinstance(ff.get("protagonist"), dict) else {}
        cards = normalize_cards(src.cards if src else {})
        d = DIRECTION_BY_ID.get(str(ff.get("direction")), {})
        fid = FIDELITY.get(str(ff.get("fidelity")), FIDELITY["moderate"])
        lab = {x["key"]: x["label"] for x in d.get("slots") or []}
        idea = "；".join(f"{lab.get(k, k)}：{v}" for k, v in (ff.get("slots") or {}).items()) or (book.premise or "")
        title = book.title
        existing = {c.name: c for c in common.cards(s, book_id, include_deprecated=True)}
        meta = {**common.kit_meta(s, book), "name": prot.get("name") or ""}
    w = cards["world"]
    user = render("fanfic_oc", title=title, source_title=ff.get("source_title") or "原著", fidelity_label=fid["label"],
                  direction=f"{d.get('label', '')}：{d.get('desc', '')}" if d else "未指定",
                  oc_type=OC_TYPES.get(str(prot.get("oc_type")), "穿越者"), oc_name=prot.get("name") or "（未定）",
                  brief=prot.get("brief") or "（无）", entry_event=prot.get("entry_event") or "（未定）", idea=idea[:600] or "（无）",
                  world=(w["summary"] + "；" + "；".join(w["rules"][:8])) or "（原著资料没有世界观）",
                  characters="\n".join(f"- {_char_line(c, 'strict')}" for c in cards["characters"][:10]) or "（无）")
    ctx.progress(20, "设计原创主角")
    out = get_gateway().chat_json("fanfic_oc", system_prompt("bible"), user, role="planner", meta=meta)
    if not isinstance(out, dict) or not str(out.get("name") or prot.get("name") or "").strip():
        raise FanficError("模型没有给出原创主角")
    name = _s(prot.get("name") or out.get("name"), 20)
    data = {k: v for k, v in (out.get("data") or {}).items() if v not in (None, "", [])} if isinstance(out.get("data"), dict) else {}
    data.update({"role": "protagonist", "origin": "oc", "oc_type": prot.get("oc_type") or data.get("oc_type") or "transmigrator"})
    if prot.get("entry_event"):
        data["entry_event"] = prot["entry_event"]
    with session_scope() as s:
        if existing:
            bible_ops.snapshot(s, book_id, "生成原创主角前")
        c = s.exec(select(Card).where(Card.book_id == book_id, Card.name == name)).first()
        if c is not None and c.locked:
            raise FanficError("同名设定卡已锁定，不能覆盖", 409)
        if c is None:
            c = Card(book_id=book_id, type="character", name=name, summary=_s(out.get("summary"), 300), data=data, known_by=[name])
        else:
            from app.services import card_versions

            card_versions.push(c, "生成原创主角前")
            c.summary = _s(out.get("summary"), 300) or c.summary
            c.data = {**(c.data or {}), **data}
        s.add(c)
        b = s.get(Book, book_id)
        if b is not None and isinstance(b.fanfic, dict):
            b.fanfic = {**b.fanfic, "protagonist": {**(b.fanfic.get("protagonist") or {}), "source": "oc", "name": name, "card_id": None}}
            s.add(b)
        s.commit()
        s.refresh(c)
        if b is not None and isinstance(b.fanfic, dict):
            b.fanfic = {**b.fanfic, "protagonist": {**b.fanfic["protagonist"], "card_id": c.id}}
            s.add(b)
            s.commit()
        return {"card_id": c.id, "name": c.name, "summary": c.summary, "data": c.data,
                "ai_filled": [str(x) for x in out.get("ai_filled") or []][:12]}
