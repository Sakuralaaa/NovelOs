"""v0.9.3 拆书工作台：在 v0.7 深度拆解基础上，拆出分模块产物并存成拆书项目（原文不入库）。

- 产物：structure / characters / golden_finger / selling_points / pacing_chart / reusable。
- 去专名：原书书名、作者，以及模型回报的专有名词，在产物里一律替换成「某」类泛称。
- 查重：产物每条与原文做 8 字 n-gram 比对，有连续 8 字相同的条目删掉，记 warnings。
- 原文只留 8 字片段的 crc32 指纹（不可还原原文），写进书的设定条目时再比一次。
"""

from __future__ import annotations

import json
import zlib
from typing import Any

from sqlmodel import select

from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Card, RankItem, RankTeardown, Teardown
from app.services import bible_ops, common
from app.services.common import NotFound
from app.services.imitate import OVERLAP_N, _norm, overlap_segments
from app.skills.loader import render, system_prompt

SOURCES = ("rank_book", "paste", "txt")
MAX_TEXT = 20000
PROMPT_TEXT = 16000  # 进提示词的原文上限（查重和指纹用全文）
MAX_PACING = 60
MODULES = ("structure", "characters", "golden_finger", "selling_points", "pacing_chart", "reusable")
PARTS = ("characters", "golden_finger", "reusable", "selling_points")
SOURCE_LABEL = {"rank_book": "（一本榜单书）", "paste": "（作者粘贴的原文）", "txt": "（作者上传的 TXT 前几章）"}
NAME_MASK = "某"


class TeardownError(ValueError):
    def __init__(self, msg: str, status: int = 400) -> None:
        super().__init__(msg)
        self.status = status


# ------------------------------------------------------------------ 工具

def _s(v: Any, n: int = 200) -> str:
    if isinstance(v, (list, tuple)):
        v = "；".join(str(x) for x in v if x)
    return str(v or "").strip()[:n]


def _strs(v: Any, k: int, n: int) -> list[str]:
    if isinstance(v, str):
        v = [v]
    return [str(x).strip()[:n] for x in (v if isinstance(v, list) else []) if str(x or "").strip()][:k]


def _clamp(v: Any) -> int:
    try:
        return max(1, min(5, int(round(float(v)))))
    except (TypeError, ValueError):
        return 1


def fingerprint(text: str, n: int = OVERLAP_N) -> list[int]:
    t = _norm(text)
    return sorted({zlib.crc32(t[i:i + n].encode("utf-8")) for i in range(max(0, len(t) - n + 1))})


def fp_hits(text: str, fp: set[int], n: int = OVERLAP_N) -> int:
    t = _norm(text)
    return sum(1 for i in range(max(0, len(t) - n + 1)) if zlib.crc32(t[i:i + n].encode("utf-8")) in fp)


def _mask(text: str, names: list[str]) -> str:
    for nm in names:
        if nm and len(nm) >= 2:
            text = text.replace(nm, NAME_MASK)
    return text


def _leaves(obj: Any) -> str:
    if isinstance(obj, dict):
        return "\n".join(_leaves(v) for v in obj.values())
    if isinstance(obj, list):
        return "\n".join(_leaves(v) for v in obj)
    return str(obj or "")


def check_create(source: str, book_id_ext: str | None, text: str | None) -> None:
    if source not in SOURCES:
        raise TeardownError("source 只能是 rank_book / paste / txt", 422)
    body = (text or "").strip()
    if len(_norm_ws(body)) > MAX_TEXT:
        raise TeardownError(f"原文超过 {MAX_TEXT} 字，请删减后再拆")
    if source == "rank_book":
        if not book_id_ext:
            raise TeardownError("rank_book 需要 book_id_ext")
        with session_scope() as s:
            if s.exec(select(RankItem).where(RankItem.book_id_ext == book_id_ext)).first() is None:
                raise TeardownError(f"榜单里没有这本书：{book_id_ext}", 404)
    elif not body:
        raise TeardownError("请粘贴要拆的原文")


def _norm_ws(t: str) -> str:
    return "".join(t.split())


def _rank_material(book_id_ext: str) -> tuple[dict[str, Any], str]:
    with session_scope() as s:
        row = s.exec(select(RankItem).where(RankItem.book_id_ext == book_id_ext).order_by(RankItem.id.desc())).first()  # type: ignore[union-attr]
        if row is None:
            raise NotFound(f"榜单里没有这本书：{book_id_ext}")
        td = s.exec(select(RankTeardown).where(RankTeardown.book_id_ext == book_id_ext).order_by(RankTeardown.id.desc())).first()  # type: ignore[union-attr]
        info = {"title": row.title, "author": row.author or "", "category": row.category or "", "tags": list(row.tags or []),
                "abstract": row.abstract or "", "teardown": (td.teardown if td else None) or {}, "deep": (td.deep if td else None) or {}}
    return info, info["abstract"]


# ------------------------------------------------------------------ 规整产物

def _clean_result(data: dict[str, Any], names: list[str], text: str) -> tuple[dict[str, Any], list[str]]:
    warns: list[str] = []
    dropped = 0

    def ok(s: str, where: str) -> bool:
        nonlocal dropped
        if text and overlap_segments(s, text):
            dropped += 1
            warns.append(f"{where}：和原文有连续 {OVERLAP_N} 字相同，已删除")
            return False
        return True

    def m(v: Any, n: int = 200) -> str:
        return _mask(_s(v, n), names)

    st = data.get("structure") if isinstance(data.get("structure"), dict) else {}
    structure = {"opening": m(st.get("opening"), 200), "rhythm": m(st.get("rhythm"), 200),
                 "chapter_hooks": [_mask(x, names) for x in _strs(st.get("chapter_hooks"), 8, 60)]}
    for k in ("opening", "rhythm"):
        if structure[k] and not ok(structure[k], f"结构·{k}"):
            structure[k] = ""
    structure["chapter_hooks"] = [x for x in structure["chapter_hooks"] if ok(x, "章末钩子")]

    chars = []
    for c in data.get("characters") or []:
        if not isinstance(c, dict):
            continue
        it = {"role": m(c.get("role"), 20) or "配角", "template": m(c.get("template"), 160),
              "traits": [_mask(x, names) for x in _strs(c.get("traits"), 5, 12)], "function": m(c.get("function"), 80)}
        if it["template"] and ok(_leaves(it), f"人设模板「{it['role']}」"):
            chars.append(it)
    gf = data.get("golden_finger") if isinstance(data.get("golden_finger"), dict) else {}
    golden = {k: m(gf.get(k), 200) for k in ("mechanism", "limits", "growth", "payoff")}
    for k in list(golden):
        if golden[k] and not ok(golden[k], f"金手指·{k}"):
            golden[k] = ""
    sps = [x for x in (_mask(x, names) for x in _strs(data.get("selling_points"), 8, 60)) if ok(x, "卖点")]
    pacing = []
    for i, p in enumerate(data.get("pacing_chart") or [], 1):
        if not isinstance(p, dict):
            continue
        try:
            ch = int(p.get("chapter") or i)
        except (TypeError, ValueError):
            ch = i
        pacing.append({"chapter": max(1, ch), "title": m(p.get("title"), 30), "conflict": _clamp(p.get("conflict")),
                       "payoff": _clamp(p.get("payoff")), "hook": _clamp(p.get("hook")), "note": m(p.get("note"), 40)})
    pacing.sort(key=lambda x: x["chapter"])
    seen: set[int] = set()
    pacing = [p for p in pacing if not (p["chapter"] in seen or seen.add(p["chapter"]))][:MAX_PACING]  # type: ignore[func-returns-value]
    for p in pacing:  # 章标题常与原文一致：只做专名遮挡；note 要过查重
        if p["note"] and text and overlap_segments(p["note"], text):
            p["note"] = ""
    reusable = []
    for r in data.get("reusable") or []:
        if not isinstance(r, dict):
            continue
        it = {"name": m(r.get("name"), 20), "pattern": m(r.get("pattern"), 160), "how_to_use": m(r.get("how_to_use"), 160)}
        if it["name"] and it["pattern"] and ok(_leaves(it), f"套路「{it['name']}」"):
            reusable.append(it)
    if dropped:
        warns.insert(0, f"共删除 {dropped} 条与原文过相似的产物")
    return {"structure": structure, "characters": chars, "golden_finger": golden, "selling_points": sps,
            "pacing_chart": pacing, "reusable": reusable}, warns


def _modules(result: dict[str, Any]) -> list[str]:
    out = []
    for k in MODULES:
        v = (result or {}).get(k)
        if isinstance(v, dict) and any(x for x in v.values()):
            out.append(k)
        elif isinstance(v, list) and v:
            out.append(k)
    return out


def teardown_out(t: Teardown) -> dict[str, Any]:
    from app.api.schemas import iso

    return {"id": t.id, "title": t.title, "source": t.source, "book_id_ext": t.book_id_ext, "chars": t.chars,
            "result": t.result or {}, "warnings": list(t.warnings or []), "model": t.model, "created_at": iso(t.created_at)}


def teardown_brief(t: Teardown) -> dict[str, Any]:
    from app.api.schemas import iso

    return {"id": t.id, "title": t.title, "source": t.source, "book_id_ext": t.book_id_ext, "chars": t.chars,
            "created_at": iso(t.created_at), "warnings_count": len(t.warnings or []), "modules": _modules(t.result or {})}


# ------------------------------------------------------------------ 拆书

def create(source: str, book_id_ext: str | None, text: str | None, title: str | None, ctx: JobContext) -> dict[str, Any]:
    check_create(source, book_id_ext, text)
    body = (text or "").strip()
    meta_lines: list[str] = []
    names: list[str] = []
    material = body
    auto_title = ""
    if source == "rank_book":
        info, abstract = _rank_material(str(book_id_ext))
        auto_title = info["title"]
        names += [info["title"], info["author"]]
        meta_lines.append(f"题材：{info['category']}；标签：{'、'.join(info['tags'][:8])}")
        meta_lines.append(f"简介（只用来理解，不要沿用词句）：{abstract[:300]}")
        if info["teardown"]:
            meta_lines.append("已有的结构拆解（v0.7）：" + json.dumps(info["teardown"], ensure_ascii=False)[:1500])
        if info["deep"] and not body:
            meta_lines.append("已有的试读深度拆解：" + json.dumps(info["deep"], ensure_ascii=False)[:2000])
        if not body:
            material = abstract
    from app.services.imitate import split_chapters

    chapters = split_chapters(material) if material else []
    ctx.progress(15, "拆书中：结构、人设、金手指、节奏")
    user = render("teardown_project", source_label=SOURCE_LABEL.get(source, ""), meta="\n".join(meta_lines) or "（无元信息）",
                  text=material[:PROMPT_TEXT] or "（没有正文，只按上面的元信息拆）",
                  notes=f"材料约 {len(_norm_ws(material))} 字，识别出 {len(chapters)} 章。")
    data = get_gateway().chat_json("teardown_project", system_prompt("teardown_project"), user,
                                   meta={"chapters": len(chapters) or 3, "names": names})
    if not isinstance(data, dict):
        raise ValueError("模型没有返回拆书结果")
    ctx.progress(75, "去专名、和原文查重")
    names += _strs(data.get("names"), 30, 20)
    names = sorted({n for n in names if n and len(n) >= 2}, key=len, reverse=True)
    result, warns = _clean_result(data, names, material)
    if not _modules(result):
        raise ValueError("拆书结果为空，请换一段原文或换个模型重试")
    with session_scope() as s:
        n = len(list(s.exec(select(Teardown.id)))) + 1
        row = Teardown(title=_s(title, 60) or auto_title or f"拆书 #{n}", source=source,
                       book_id_ext=book_id_ext if source == "rank_book" else None, chars=len(_norm_ws(material)),
                       result=result, warnings=warns, fingerprint=fingerprint(material), names=names,
                       model=_model_name())
        s.add(row)
        s.commit()
        s.refresh(row)
        return {"teardown": teardown_out(row), "teardown_id": row.id}


def _model_name() -> str:
    from app.llm.gateway import resolve_targets

    with session_scope() as s:
        ts = resolve_targets(s, "reviewer")
    return f"{ts[0].name}/{ts[0].model}" if ts else "mock"


def get(teardown_id: int) -> Teardown:
    with session_scope() as s:
        t = s.get(Teardown, teardown_id)
        if t is None:
            raise NotFound("拆书记录不存在")
        return t


# ------------------------------------------------------------------ 转选题 / 转设定

def seed_from(t: Teardown, notes: str = "") -> dict[str, Any]:
    r = t.result or {}
    gf = r.get("golden_finger") or {}
    sps = list(r.get("selling_points") or [])
    prot = next((c for c in r.get("characters") or [] if "主角" in str(c.get("role"))), None) or next(iter(r.get("characters") or []), None)
    st = r.get("structure") or {}
    mech = _s(gf.get("mechanism"), 300)
    logline = _s("；".join(x for x in [mech and f"核心机制：{mech}", sps[0] if sps else "", notes] if x), 500) or "按拆书产物立项的新选题"
    src: dict[str, Any] = {"type": "teardown", "ref": f"teardown#{t.id}"}
    if t.book_id_ext:
        with session_scope() as s:
            if s.exec(select(RankItem).where(RankItem.book_id_ext == t.book_id_ext)).first() is not None:
                src["book_id_ext"] = t.book_id_ext
    return {"title": f"拆书立项#{t.id}", "logline": logline,
            "protagonist": _s(prot.get("template"), 300) if prot else "", "mechanism": mech,
            "opening": _s(st.get("opening"), 500), "selling_points": [x[:60] for x in sps[:8]], "genre": "",
            "gender": None, "source": src}


def _tag_idea(idea_id: int, teardown_id: int) -> dict[str, Any]:
    from app.api.schemas import idea_out
    from app.models.tables import Idea

    with session_scope() as s:
        i = s.get(Idea, idea_id)
        assert i is not None
        i.source = {**(i.source or {}), "type": "teardown", "kind": "teardown", "ref": f"teardown#{teardown_id}", "teardown_id": teardown_id}
        s.add(i)
        s.commit()
        s.refresh(i)
        return idea_out(i)


def to_idea_direct(teardown_id: int, notes: str = "") -> dict[str, Any]:
    from app.services import seed_ideas

    t = get(teardown_id)
    res = seed_ideas.seed_direct(seed_from(t, notes))
    return {"idea": _tag_idea(int(res["idea"]["id"]), teardown_id)}


def to_idea_expand(teardown_id: int, notes: str, ctx: JobContext) -> dict[str, Any]:
    from app.services import seed_ideas

    t = get(teardown_id)
    res = seed_ideas.seed_expand(seed_from(t, notes), ctx)
    idea = _tag_idea(int(res["idea_id"]), teardown_id)
    return {"idea": idea, "idea_id": idea["id"]}


def _draft_cards(t: Teardown, parts: list[str]) -> list[dict[str, Any]]:
    r = t.result or {}
    tag = {"from_teardown": t.id, "draft": True}
    out: list[dict[str, Any]] = []
    if "characters" in parts:
        for c in r.get("characters") or []:
            out.append({"type": "character", "name": f"模板·{c.get('role') or '配角'}"[:40], "summary": str(c.get("template") or ""),
                        "data": {**tag, "kind": "character_template", "role": "", "traits": list(c.get("traits") or []),
                                 "function": str(c.get("function") or "")}})
    if "golden_finger" in parts:
        gf = r.get("golden_finger") or {}
        if gf.get("mechanism"):
            out.append({"type": "power", "name": "模板·金手指机制", "summary": str(gf.get("mechanism") or ""),
                        "data": {**tag, "kind": "golden_finger", "limit": gf.get("limits") or "", "growth": gf.get("growth") or "",
                                 "payoff": gf.get("payoff") or ""}})
    if "reusable" in parts:
        for x in r.get("reusable") or []:
            out.append({"type": "world", "name": f"套路·{x.get('name')}"[:40], "summary": str(x.get("pattern") or ""),
                        "data": {**tag, "kind": "reusable", "how_to_use": str(x.get("how_to_use") or "")}})
    if "selling_points" in parts and r.get("selling_points"):
        out.append({"type": "world", "name": "模板·卖点清单", "summary": "；".join(r["selling_points"]),
                    "data": {**tag, "kind": "selling_points", "items": list(r["selling_points"])}})
    return out


def to_bible(teardown_id: int, book_id: int, parts: list[str]) -> dict[str, Any]:
    from app.api.schemas import card_out

    bad = [p for p in parts if p not in PARTS]
    if not parts or bad:
        raise TeardownError(f"parts 只能是 {'/'.join(PARTS)}", 422)
    t = get(teardown_id)
    fp = set(t.fingerprint or [])
    names = list(t.names or [])
    warns: list[str] = []
    skipped = 0
    with session_scope() as s:
        common.get_book(s, book_id)
        drafts = _draft_cards(t, parts)
        if not drafts:
            return {"cards": [], "warnings": ["拆书产物里没有可写入的内容"], "skipped": 0}
        bible_ops.snapshot(s, book_id, f"拆书#{teardown_id} 写入设定前")
        existing = {c.name for c in common.cards(s, book_id, include_deprecated=True)}
        made: list[Card] = []
        for d in drafts:
            d["name"], d["summary"] = _mask(d["name"], names), _mask(d["summary"], names)
            text = d["name"] + "\n" + d["summary"] + "\n" + _leaves({k: v for k, v in d["data"].items() if k not in ("from_teardown", "draft")})
            if fp and fp_hits(text, fp):
                skipped += 1
                warns.append(f"「{d['name']}」和原文有连续 {OVERLAP_N} 字相同，已跳过")
                continue
            name, k = d["name"], 1
            while name in existing:
                k += 1
                name = f"{d['name']}{k}"[:40]
            existing.add(name)
            c = Card(book_id=book_id, type=d["type"], name=name, summary=d["summary"], data=d["data"], known_by=[])
            s.add(c)
            made.append(c)
        s.commit()
        for c in made:
            s.refresh(c)
        return {"cards": [card_out(c) for c in made], "warnings": warns, "skipped": skipped}


def delete(teardown_id: int) -> None:
    with session_scope() as s:
        t = s.get(Teardown, teardown_id)
        if t is None:
            raise NotFound("拆书记录不存在")
        s.delete(t)
        s.commit()


def list_all() -> list[dict[str, Any]]:
    with session_scope() as s:
        return [teardown_brief(t) for t in s.exec(select(Teardown).order_by(Teardown.id.desc()))]  # type: ignore[union-attr]

