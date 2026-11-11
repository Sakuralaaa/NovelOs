from app.config import LintThresholds
from app.lint.banned_zh import BANNED_PATTERNS
from app.lint.humanlint import (
    bare_dialogue_analysis, banned_hits, dialogue_ratio, lint_chapter, repeated_ngrams, sentence_stats, summary_analysis,
)

TH = LintThresholds()


def test_banned_list_size() -> None:
    assert len(BANNED_PATTERNS) >= 60


def test_banned_hits_longest_first_and_counts() -> None:
    hits = {h["word"]: h["count"] for h in banned_hits("他嘴角勾起一抹冷笑，不禁后退。她眼中闪过一丝寒意。")}
    assert hits.get("嘴角勾起一抹") == 1
    assert "一抹" not in hits  # 被长词覆盖，不重复计数
    assert hits.get("不禁") == 1
    assert hits.get("眼中闪过一丝") == 1


def test_natural_talk_patterns_narration_only() -> None:
    text = "这不是恐惧，而是愤怒。他微微点头。领口别着枚旧胸针——地摊上淘的。然而，雨停了。对于他来说，这意味着结束。"
    words = {h["word"] for h in banned_hits(text)}
    assert "翻案腔：不是X而是Y" in words
    assert "修饰副词+动作" in words
    assert "叙述破折号" in words
    assert "翻译腔：然而/此外/与此同时" in words
    assert "翻译腔：对于……来说" in words
    assert "翻译腔：这意味着" in words
    # 台词里的翻案腔与破折号不计
    quoted = "他说：“这不是钱的事，而是脸面——你懂吗？”"
    words2 = {h["word"] for h in banned_hits(quoted)}
    assert "翻案腔：不是X而是Y" not in words2 and "叙述破折号" not in words2


def test_dialogue_ratio() -> None:
    assert dialogue_ratio("“你好。”他说。") > 0.4
    assert dialogue_ratio("没有对话。") == 0


def test_sentence_stats_short() -> None:
    st = sentence_stats("他走了。她哭了。门关了。天黑了。他把伞往墙角一靠，拉开椅子坐下，椅腿在水泥地上刮出一道刺耳的声音。")
    assert st["short_ratio"] >= 0.75
    assert st["avg"] > 0


def test_bare_dialogue() -> None:
    bare_text = "“钱呢？”\n“没有。”\n“那就走。”"
    r, paras = bare_dialogue_analysis(bare_text)
    assert r == 1.0 and paras == [0, 1, 2]
    dressed = "他把单据拍在桌上，用手指按住一角：“钱呢？”\n对面的人眼皮都没抬：“没有。”"
    r2, _ = bare_dialogue_analysis(dressed)
    assert r2 == 0.0
    # 乒乓对白：上一段的动作只“引出”第一句，第二句仍算裸对白
    pingpong = "他把单据拍在桌上。\n“钱呢？”\n“没有。”\n雨停了。"
    r3, paras3 = bare_dialogue_analysis(pingpong)
    assert r3 == 0.5 and paras3 == [2]


def test_summary_ratio() -> None:
    r, paras = summary_analysis("经过一番周旋，事情很快有了眉目，于是众人散去。\n他推开门，雨水灌进来。")
    assert r >= 0.5 and paras == [0]


def test_repeated_ngrams_book_wide_and_names_excluded() -> None:
    cur = "林照推开那扇沉重的铁门。屋里一下子静了下来。"
    others = ["屋里一下子静了下来，没人说话。", "屋里一下子静了下来。林照推开门。"]
    reps = repeated_ngrams(cur, others, TH, exclude_names=["林照"])
    texts = [r["text"] for r in reps]
    assert any("一下子静了" in t for t in texts)
    assert not any("林照" in t for t in texts)


def test_lint_chapter_fields_and_thresholds() -> None:
    good = ("林照推开七号仓的铁门时，柴油味混着鱼腥扑了一脸，他在门口站定，把屋里的人数了一遍，才抬脚往里走。\n\n"
            "钱少坤转着手上的扳指，开口时连看都没看他：“东西交出来，今天的事我当没看见。”\n\n"
            "林照没接话，把那张皱巴巴的单据拍在桌上，用两根手指按住一角。“账得算清楚。”")
    r = lint_chapter(good, TH, chapter_number=1)
    d = r.to_dict()
    for k in ("ai_score", "dialogue_ratio", "repeated_ngrams", "banned_hits", "warnings",
              "avg_sentence_len", "short_sentence_ratio", "bare_dialogue_ratio", "summary_ratio"):
        assert k in d
    assert 0 <= r.ai_score <= 100
    assert r.bare_dialogue_ratio == 0.0
    bad = "\n".join(["“走吗？”", "“走。”", "“齐了？”", "“齐了。”", "经过一番周旋，事情很快办妥，于是随后散了。",
                     "他不禁嘴角勾起一抹冷笑，仿佛一切尽在掌握。"])
    rb = lint_chapter(bad, TH, chapter_number=1)
    assert rb.ai_score > r.ai_score
    assert rb.needs_thicken(TH)
    assert any("裸对白" in w for w in rb.warnings)
    assert any("概述" in w for w in rb.warnings)


def test_first_three_chapters_long_monologue() -> None:
    para = "他想起了很多年前的事情" * 30
    r = lint_chapter(para, TH, chapter_number=2)
    assert any("前三章" in w for w in r.warnings)
    r2 = lint_chapter(para, TH, chapter_number=10)
    assert not any("前三章" in w for w in r2.warnings)
