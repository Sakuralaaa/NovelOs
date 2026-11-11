from app.services.changes import ChangeSet, check_against_ledger, parse_changes, split_output
from app.services.review import build_review, compute_scores, deterministic_issues, quote_in_text, validate_issues

CONTENT = "林照推开铁门，雨水顺着帽檐往下淌。\n\n钱少坤转着扳指：“东西交出来。”\n\n林照没接话。"


def test_quote_in_text_whitespace_tolerant() -> None:
    assert quote_in_text("林照推开铁门，雨水顺着帽檐往下淌。", CONTENT)
    assert quote_in_text("林照推开铁门， 雨水顺着 帽檐往下淌", CONTENT)
    assert not quote_in_text("他一拳打碎了整座山门。", CONTENT)
    assert not quote_in_text("林照", CONTENT)  # 太短，不算证据


def test_validate_issues_drops_fake_quotes() -> None:
    raw = {"issues": [
        {"severity": "high", "dimension": "character", "quote": "钱少坤转着扳指", "comment": "ok"},
        {"severity": "mid", "dimension": "payoff", "quote": "他一拳打碎了整座山门。", "comment": "编造"},
        {"severity": "weird", "dimension": "nope", "quote": "林照没接话。", "comment": "规范化"},
    ]}
    kept, dropped = validate_issues(raw, CONTENT)
    assert dropped == 1
    assert len(kept) == 2
    assert kept[1]["severity"] == "low" and kept[1]["dimension"] == "coherence"


def test_scores_computed_by_program() -> None:
    issues = [{"severity": "high", "dimension": "hook", "quote": "x", "comment": ""},
              {"severity": "mid", "dimension": "pacing", "quote": "x", "comment": ""}]
    sc = compute_scores(issues)
    assert sc["hook"] == 75 and sc["pacing"] == 90 and sc["payoff"] == 100
    r = build_review(issues)
    assert r["passed"] is False
    assert build_review([])["passed"] is True and build_review([])["scores"]["overall"] == 100


def test_appearance_guard() -> None:
    iss = deterministic_issues(CONTENT, "林照", ["林照", "老周"], 1)
    assert any("老周" in i["comment"] and i["severity"] == "high" for i in iss)
    assert all(quote_in_text(i["quote"], CONTENT) for i in iss)


def test_split_and_parse_changes() -> None:
    out = "正文第一段。\n\n---CHANGES---\n```json\n" + (
        '{"new_entities":[{"type":"character","name":"斗笠客","summary":"神秘人"},{"type":"bogus","name":"铜钥匙"}],'
        '"state_changes":[{"entity":"林照","key":"处境","value":"受伤"},{"entity":"","key":"x","value":"y"}],'
        '"foreshadow":[{"action":"plant","id":null,"desc":"豁口"},{"action":"explode","desc":"x"}]}'
    ) + "\n```"
    body, raw = split_output(out)
    assert body == "正文第一段。"
    cs, warns = parse_changes(raw)
    assert [e.name for e in cs.new_entities] == ["斗笠客", "铜钥匙"]
    assert cs.new_entities[1].type == "character"  # 非法类型归一
    assert len(cs.state_changes) == 1 and len(cs.foreshadow) == 1
    assert len(warns) == 2


def test_parse_changes_missing_or_invalid() -> None:
    cs, w = parse_changes(None)
    assert cs == ChangeSet() and w
    cs, w = parse_changes("not json")
    assert cs == ChangeSet() and "JSON" in w[0]


def test_check_against_ledger() -> None:
    cs, _ = parse_changes('{"new_entities":[{"name":"林照"},{"name":"新人"}],'
                          '"state_changes":[{"entity":"路人甲","key":"状态","value":"死亡"}],'
                          '"foreshadow":[{"action":"advance","id":null,"desc":"铜扣账本上的豁口"},'
                          '{"action":"resolve","id":999,"desc":"不存在的伏笔"}]}')
    out, warns = check_against_ledger(cs, {"林照"}, {7: "铜扣账本上的豁口"})
    names = [e.name for e in out.new_entities]
    assert "林照" not in names and "新人" in names and "路人甲" in names
    assert out.foreshadow[0].id == 7 and len(out.foreshadow) == 1
    assert any("未登记实体" in w for w in warns) and any("找不到" in w for w in warns)
