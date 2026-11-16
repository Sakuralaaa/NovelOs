"""v0.9.4 lint 阈值校准统计：对 work/samples、work/tuning 下的样章跑 lint，按平台档统计命中率。

用法：cd backend && python scripts/lint_calibration.py [--json out.json]
只读样章、纯代码，不调模型。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import LintThresholds  # noqa: E402
from app.lint.humanlint import count_words, lint_chapter  # noqa: E402

ROOT = Path(__file__).resolve().parents[3] / "work"


def load_samples() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for p in sorted((ROOT / "samples").glob("*.txt")):
        out.append((f"samples/{p.name}", p.read_text("utf-8")))
    for p in sorted((ROOT / "tuning").glob("*.txt")):
        out.append((f"tuning/{p.name}", p.read_text("utf-8")))
    md = ROOT / "tuning" / "追读版第1-3章.md"
    if md.exists():
        parts = re.split(r"^## (第\d+章.*)$", md.read_text("utf-8"), flags=re.M)
        for i in range(1, len(parts) - 1, 2):
            out.append((f"tuning/追读版·{parts[i].strip()}", parts[i + 1].strip()))
    # 去重：追读版第1-3章与 b3_ch1-3.txt 正文相同
    seen: set[str] = set()
    uniq = []
    for name, text in out:
        key = re.sub(r"\s", "", text)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((name, text))
    return uniq


def warn_key(w: str) -> str:
    return re.split(r"[ 0-9（：:「]", w, maxsplit=1)[0][:10]


def main() -> None:
    th = LintThresholds()
    rows = []
    for plat in ("fanqie", "qidian"):
        for name, text in load_samples():
            r = lint_chapter(text, th, (), ("叶承", "韩铎"), 1 if "ch1" in name or "第1章" in name else 2, platform=plat)
            kinds = Counter(t["kind"] for t in r.fix_targets)
            rows.append({
                "platform": plat, "sample": name, "words": count_words(text), "ai_score": r.ai_score,
                "warnings": len(r.warnings), "warn_keys": [warn_key(w) for w in r.warnings],
                "fix_targets": len(r.fix_targets), "fix_kinds": dict(kinds), "long_paragraphs": len(r.long_paragraphs),
                "waterfall_run": r.waterfall_run, "craft_problems": r.craft_problem_count(),
                "needs_patch": r.needs_patch(th), "intens_over": [d["word"] for d in r.intensifiers if d["over"]],
                "long_flagged": r.long_para_flagged, "numeric": [i["comment"] for i in r.numeric_issues],
                "tier": r.tier, "short_ratio": r.short_sentence_ratio, "avg_sent": r.avg_sentence_len, "dialogue": r.dialogue_ratio,
            })
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    if len(sys.argv) > 2 and sys.argv[1] == "--json":
        Path(sys.argv[2]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    main()
