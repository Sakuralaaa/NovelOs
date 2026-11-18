"""v0.18.0 卖点兑现与阻力换型。"""

from app.services import outline
from app.skills.loader import render


def _ch(conflict, ctype=""):
    return {"title": "x", "conflict": conflict, "conflict_type": ctype}


def test_conflict_kind_infers_paperwork():
    assert outline.conflict_kind({"conflict": "孙德海拿着复核单不肯签字"}) == "规则刁难"
    assert outline.conflict_kind({"conflict": "赵天磊带人堵在后巷"}) == ""
    assert outline.conflict_kind({"conflict": "复核", "conflict_type": "擂台比试"}) == "擂台比试"


def test_pacing_audit_flags_paperwork_and_same_conflict():
    chs = [{**_ch("教务处不收报名表"), "number": 1}, {**_ch("年级组要复核资格"), "number": 2},
           {**_ch("武籍房说档案除名"), "number": 3}, {**_ch("对手当面挑衅", "武力挑衅"), "number": 4}]
    issues = outline.pacing_audit(chs)
    assert any("手续" in x for x in issues)
    assert any("原地打转" in x for x in issues)


def test_normalize_promises_caps_due_chapter():
    ps = outline.normalize_promises([{"what": "擂台一拳打落赵天磊", "by": 56}, "一夜加点顶三年", {"what": ""}])
    assert ps[0] == {"what": "擂台一拳打落赵天磊", "by": outline.PROMISE_FIRST_BY}
    assert ps[1]["by"] == outline.PROMISE_CORE_BY
    assert len(ps) == 2


def test_draft_audit_requires_promises():
    data = {"book": {}, "arcs": [{"chapters": [_ch("对手挑衅", "武力挑衅"), _ch("猎杀", "猎杀探险")]}]}
    assert any("promises" in x for x in outline.draft_audit(data))
    data["book"]["promises"] = [{"what": "打脸", "by": 2}]
    assert outline.draft_audit(data) == []


def test_promises_text_marks_due():
    txt = outline.promises_text([{"what": "A", "by": 3}, {"what": "B", "by": 10}], 5)
    assert "A（已到期" in txt and "B（最晚第10章兑现）" in txt


def test_reader_prompt_has_ledger():
    out = render("reader", number=3, chapter_plan="p", content="c", persona="读者", context="ctx", ledger="LEDGER_X")
    assert "LEDGER_X" in out and "原地打转" in out


def test_name_note_lists_overused():
    from app.db import session_scope
    from app.services import common

    with session_scope() as s:
        note = common.name_note(s)
    assert "林烬" in note
