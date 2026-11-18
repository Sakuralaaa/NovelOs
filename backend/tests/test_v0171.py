"""v0.17.1 规划与实写对齐：已结算面板、跨章口头禅计数、章纲衔接合并。"""

from app.lint.humanlint import catchphrase_report, habit_report, window_allow
from app.models.tables import Chapter, OutlineNode
from app.services import continuity


def test_settled_lines_picks_panel_rows():
    a = Chapter(book_id=1, number=1, title="一", content="雨很大。\n【雨夜节点改写成功】\n他笑了。\n【血统承载力提升：B → B+】")
    b = Chapter(book_id=1, number=2, title="二", content="【雨夜节点改写成功】\n“【不是面板】”他说。")
    lines = continuity.settled_lines([b, a])
    assert lines == ["第1章：【雨夜节点改写成功】", "第1章：【血统承载力提升：B → B+】"]
    assert "不再结算" in continuity.settled_block([a])


def test_window_allow_counts_previous_chapters():
    assert window_allow("这波不亏", 1, {"这波不亏": 2}, 2) == 0
    assert window_allow("这波不亏", 1, {}, 2) == 1
    cps = catchphrase_report("他说这波不亏。", {"江叙": ["这波不亏"]}, 1, {"这波不亏": 2})
    assert cps[0]["over"] and cps[0]["allow"] == 0
    cps = catchphrase_report("他说这波不亏。", {"江叙": ["这波不亏"]}, 1)
    assert not cps[0]["over"]
    hab = habit_report("他猛搓后颈。又搓后颈。", {"楚天骄": ["搓后颈"]}, 2, {"搓后颈": 2})
    assert hab[0]["over"] and hab[0]["allow"] == 1


def test_merge_only_known_fields_and_drops_scenes():
    node = OutlineNode(book_id=1, level="chapter", order=2, title="旧", summary="",
                       beats={"goal": "逃出尼伯龙根", "conflict": "死侍", "scenes": [{"goal": "x"}]})
    assert continuity._merge(node, {"goal": "面对执行部问询", "result": "被带回学院", "outcome": "bad", "evil": "x"})
    assert node.beats["goal"] == "面对执行部问询" and "scenes" not in node.beats
    assert "evil" not in node.beats and "outcome" not in node.beats
    assert node.summary.startswith("面对执行部问询")
    assert node.versions and node.versions[-1]["beats"]["goal"] == "逃出尼伯龙根"
    assert not continuity._merge(node, {"goal": "面对执行部问询"})
