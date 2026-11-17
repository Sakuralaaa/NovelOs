"""v0.12 E6 批量质检 mock：章节标题候选。确定性输出，只用正文里出现过的人名。"""

from __future__ import annotations

import json
import re
from typing import Any


def mock_batch_chapter_title(meta: dict[str, Any]) -> str:
    text = str(meta.get("text") or "")
    number = int(meta.get("number") or 1)
    names = [n for n in (meta.get("names") or []) if n and n in text]
    who = names[0] if names else "他"
    objs = [w for w in ("账本", "钟声", "门口", "灵石", "拳头", "长刀", "信", "钥匙", "雨夜") if w in text]
    obj = objs[0] if objs else "旧账"
    titles = [f"{obj}里的第{number}个秘密"[:14], f"{who}不肯低头", f"{who}，这次我来"]
    if re.search(r"[“”]", text):
        titles[2] = f"一句话，{who}翻了盘"
    return json.dumps({"titles": titles, "reason": "悬念落在具体物件上，读者想知道里面是什么（演示）"}, ensure_ascii=False)


BATCH_HANDLERS = {"batch_chapter_title": mock_batch_chapter_title}
