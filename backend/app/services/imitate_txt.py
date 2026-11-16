"""v0.9.2 仿写立项 TXT：识别编码 → 按「第X章 / 第X回 / Chapter N」切章 → 取前 10 章拼接（≤20000 字）。不入库。

拿到的 text 交给前端走现有 v0.7 深度拆解（/radar/items/{id}/deep）与换皮接口。
"""

from __future__ import annotations

import re
from pathlib import PurePath
from typing import Any

MAX_BYTES = 30 * 1024 * 1024
MAX_TEXT_CHARS = 20000
CHAPTERS_N = 10

_NUM = r"[0-9０-９零〇一二两三四五六七八九十百千万]+"
_CH_RX = re.compile(
    rf"^[ \t\u3000]*((?:第{_NUM}[章回节](?:[ \t\u3000:：、.\-—]*[^\n]{{0,40}})?)|(?:chapter[ \t]*\d+(?:[ \t:：.\-—]*[^\n]{{0,40}})?)"
    r"|(?:序章|楔子|引子|序言)(?:[ \t\u3000:：]*[^\n]{0,30})?)[ \t\u3000]*$",
    re.M | re.I,
)
_TITLE_LINE = re.compile(r"^[ \t\u3000]*(?:书名[:：]\s*)?《([^》\n]{1,40})》")
_TITLE_KV = re.compile(r"^[ \t\u3000]*书名[:：]\s*([^\n]{1,40})$", re.M)


class ExtractError(ValueError):
    pass


def decode(data: bytes) -> tuple[str, str]:
    """→ (文本, 编码)。BOM 优先；否则 utf-8，失败用 gb18030（兼容 gbk / gb2312）。"""
    if not data:
        raise ExtractError("文件是空的")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace"), "utf-16"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("gb18030"), "gb18030"
    except UnicodeDecodeError:
        return data.decode("gb18030", errors="replace"), "gb18030"


def split(text: str) -> list[dict[str, str]]:
    """→ [{title, body}]。没识别到章节标题时整段算一章「全文」；第一个标题前的文字（书名、简介）不算章节。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    ms = list(_CH_RX.finditer(text))
    if not ms:
        return [{"title": "全文", "body": text.strip()}]
    out = []
    for k, m in enumerate(ms):
        end = ms[k + 1].start() if k + 1 < len(ms) else len(text)
        out.append({"title": re.sub(r"\s+", " ", m.group(1)).strip(), "body": text[m.end():end].strip()})
    return out


def _chars(s: str) -> int:
    return len(re.sub(r"\s", "", s))


def guess_title(text: str, filename: str | None) -> str:
    head = text.replace("\r", "")[:2000]
    first = _CH_RX.search(head)
    pre = head[:first.start()] if first else head[:300]
    m = _TITLE_KV.search(pre) or _TITLE_LINE.search(pre)
    if m:
        return m.group(1).strip().strip("《》")
    if filename:
        stem = PurePath(filename).stem
        stem = re.sub(r"[\(（\[【].*?[\)）\]】]", "", stem)  # 去掉（全本）【作者】之类
        stem = re.sub(r"\s*(作者|by)[:：\s].*$", "", stem, flags=re.I).strip().strip("《》 ")
        if stem:
            return stem[:40]
    for line in pre.split("\n"):
        line = line.strip()
        if 2 <= len(line) <= 30:
            return line.strip("《》")
    return ""


def extract(data: bytes | None = None, text: str | None = None, filename: str | None = None) -> dict[str, Any]:
    if data is not None:
        if len(data) > MAX_BYTES:
            raise ExtractError(f"文件超过 {MAX_BYTES // 1024 // 1024}MB")
        text, enc = decode(data)
    else:
        enc = "text"
    text = (text or "").replace("\ufeff", "")
    if not text.strip():
        raise ExtractError("没有可用的正文")
    chs = split(text)
    head = chs[:CHAPTERS_N]
    parts, total, truncated = [], 0, False
    for c in head:
        block = f"{c['title']}\n\n{c['body']}".strip() if c["title"] != "全文" else c["body"]
        room = MAX_TEXT_CHARS - total - (2 if parts else 0)
        if room <= 0:
            truncated = True
            break
        if len(block) > room:
            block, truncated = block[:room], True
        parts.append(block)
        total += len(block) + (2 if len(parts) > 1 else 0)
    joined = "\n\n".join(parts)[:MAX_TEXT_CHARS]
    return {"title_guess": guess_title(text, filename), "encoding": enc, "total_chapters": len(chs) if chs[0]["title"] != "全文" else 0,
            "chapters": [{"title": c["title"], "chars": _chars(c["body"])} for c in head],
            "text": joined, "text_chars": len(joined), "truncated": truncated}
