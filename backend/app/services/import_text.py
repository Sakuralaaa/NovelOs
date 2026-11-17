"""v0.12 E1 导入已有作品：文件解码（TXT / MD / DOCX / 粘贴）、自动切卷切章、切分体检、大纲文本解析。纯函数，不碰数据库。

切章规则按顺序尝试，取第一种能切出 ≥2 章的：
1. 作者自定义正则（逐行匹配，整行是标题）；
2. 常见网文格式：第X章/回/节（含【】包裹、全角数字、中文数字）、Chapter N、序章/楔子/尾声/番外等；
3. DOCX 标题样式段落、Markdown 的 # 标题；
4. 纯序号行（「001 标题」「12. 标题」），要求序号基本连续，避免把正文里的列表当成章节。
「第X卷/部/册」单独识别为卷，归到其后的章节上。
"""

from __future__ import annotations

import hashlib
import io
import re
import statistics
import zipfile
from pathlib import PurePath
from typing import Any
from xml.etree import ElementTree as ET

from app.services.imitate_txt import decode as _decode_bytes

MAX_BYTES = 30 * 1024 * 1024
MAX_CHAPTERS = 5000
MAX_PATTERN_LEN = 200
TITLE_MAX = 50  # 标题行最长字数（超过视为正文）

_NUM = r"[0-9０-９零〇○一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]+"
# 第X章/回/节（排除「第三回合」「第五节课」这类正文）；允许【】[]包裹、标题与章号间无空格
_CH_MAIN = re.compile(
    rf"^[【\[〔（(]?\s*(第\s*({_NUM})\s*[章回节](?!合|课|节课))\s*[】\]〕）)]?(?:[ \t\u3000]*[:：、.．\-—·]*[ \t\u3000]*(.{{0,40}}))?$"
)
_CH_EN = re.compile(r"^(chapter\s*(\d{1,5}))\b[ \t:：.\-—]*(.{0,40})$", re.I)
_CH_SPECIAL = re.compile(r"^(序章|序幕|楔子|引子|序言|前言|尾声|终章|后记|完本感言|番外(?:[一二三四五六七八九十\d]+)?)(?:[ \t\u3000:：、.\-—·]*(.{0,30}))?$")
_VOL = re.compile(rf"^[【\[]?\s*(第\s*({_NUM})\s*[卷部册集](?!分))\s*[】\]]?(?:[ \t\u3000]*[:：、.．\-—·]*[ \t\u3000]*(.{{0,40}}))?$")
_VOL_ALT = re.compile(r"^(卷[一二三四五六七八九十\d]+|上卷|中卷|下卷)(?:[ \t\u3000:：、.\-—·]*(.{0,30}))?$")
_NUMBERED = re.compile(r"^(\d{1,4})(?:[ \t\u3000]*[.、．:：]|[ \t\u3000]+)[ \t\u3000]*(\S.{0,30})$")
_MD_HEAD = re.compile(r"^(#{1,3})\s+(.{1,50})$")

_TITLE_LINE = re.compile(r"^[ \t\u3000]*(?:书名[:：]\s*)?《([^》\n]{1,40})》")
_TITLE_KV = re.compile(r"^[ \t\u3000]*书名[:：]\s*([^\n]{1,40})$", re.M)
_INTRO_KV = re.compile(r"^[ \t\u3000]*(?:简介|内容简介|作品简介)[:：]?\s*$", re.M)

_CN_DIGIT = {"零": 0, "〇": 0, "○": 0, "一": 1, "壹": 1, "二": 2, "两": 2, "贰": 2, "三": 3, "叁": 3, "四": 4, "肆": 4,
             "五": 5, "伍": 5, "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}
_CN_UNIT = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}

FLAG_LABEL = {
    "empty": "空章（几乎没有正文）",
    "short": "比其它章短很多，可能是切错了或是公告/请假条",
    "long": "比其它章长很多，可能漏切了章节标题",
    "dup_title": "章节标题和前面某章重复",
    "dup_content": "正文和前面某章完全相同（重复章）",
    "gap": "章号不连续（中间可能缺章或顺序乱了）",
}


class ImportError_(ValueError):
    """导入解析错误（文件格式、正则、内容为空）。路由转 400/413/422。"""

    def __init__(self, msg: str, status: int = 400) -> None:
        super().__init__(msg)
        self.status = status


# ------------------------------------------------------------------ 数字

def cn2int(s: str) -> int | None:
    """「十二」「一百零三」「0012」「１２」→ 整数；无法解析返回 None。"""
    s = (s or "").strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if all(ch in _CN_DIGIT for ch in s):  # 「一二三」逐位写法
        return int("".join(str(_CN_DIGIT[ch]) for ch in s))
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            section += (num or 1) * _CN_UNIT[ch]
            num = 0
        elif ch == "万":
            total += (section + num) * 10000
            section, num = 0, 0
        else:
            return None
    return total + section + num


def count_words(text: str) -> int:
    return len(re.sub(r"\s", "", text or ""))


# ------------------------------------------------------------------ 读文件

def docx_paragraphs(data: bytes) -> list[tuple[str, bool]]:
    """DOCX → [(段落文字, 是否标题样式)]。只读 word/document.xml，不依赖第三方库。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        xml = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as e:
        raise ImportError_("不是有效的 .docx 文件（老版 .doc 请先另存为 .docx 或 .txt）", 422) from e
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    heading_styles: set[str] = set()
    try:
        sroot = ET.fromstring(zf.read("word/styles.xml"))
        for st in sroot.iter(f"{w}style"):
            sid = st.get(f"{w}styleId") or ""
            name_el = st.find(f"{w}name")
            name = (name_el.get(f"{w}val") if name_el is not None else "") or ""
            low = name.lower()
            if low.startswith(("heading", "title")) or name.startswith(("标题", "章节")) or st.find(f"{w}pPr/{w}outlineLvl") is not None:
                heading_styles.add(sid)
    except (KeyError, ET.ParseError):
        pass
    root = ET.fromstring(xml)
    out: list[tuple[str, bool]] = []
    for p in root.iter(f"{w}p"):
        ppr = p.find(f"{w}pPr")
        heading = False
        if ppr is not None:
            ps = ppr.find(f"{w}pStyle")
            sid = ps.get(f"{w}val") if ps is not None else ""
            heading = bool(sid) and (sid in heading_styles or sid.lower().startswith(("heading", "title")))
            heading = heading or ppr.find(f"{w}outlineLvl") is not None
        parts: list[str] = []
        for el in p.iter():
            tag = el.tag
            if tag == f"{w}t":
                parts.append(el.text or "")
            elif tag == f"{w}tab":
                parts.append("\t")
            elif tag in (f"{w}br", f"{w}cr"):
                parts.append("\n")
        out.append(("".join(parts), heading))
    return out


def read_input(data: bytes | None, text: str | None, filename: str | None) -> dict[str, Any]:
    """→ {text, format, encoding, headings}。headings：DOCX 标题样式段落 / Markdown 标题（备选切章依据）。"""
    fmt = "paste"
    enc = "text"
    headings: list[str] = []
    if data is not None:
        if len(data) > MAX_BYTES:
            raise ImportError_(f"文件超过 {MAX_BYTES // 1024 // 1024}MB，请拆成几部分分别导入", 413)
        if not data:
            raise ImportError_("文件是空的", 422)
        ext = PurePath(filename or "").suffix.lower()
        if ext == ".doc":
            raise ImportError_("暂不支持老版 .doc，请在 Word / WPS 里另存为 .docx 或 .txt 再导入", 422)
        if ext == ".docx" or data[:2] == b"PK":
            paras = docx_paragraphs(data)
            text = "\n".join(t for t, _ in paras)
            headings = [t.strip() for t, h in paras if h and t.strip() and len(t.strip()) <= TITLE_MAX]
            fmt, enc = "docx", "docx"
        else:
            text, enc = _decode_bytes(data)
            fmt = "md" if ext in (".md", ".markdown") else "txt"
    text = (text or "").replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    if fmt in ("md", "paste") and not headings:
        headings = [m.group(2).strip() for m in (_MD_HEAD.match(ln.strip()) for ln in text.split("\n")) if m]
    if not text.strip():
        raise ImportError_("没有可用的正文", 422)
    return {"text": text, "format": fmt, "encoding": enc, "headings": headings}


# ------------------------------------------------------------------ 切章

def compile_pattern(pattern: str | None) -> re.Pattern[str] | None:
    p = (pattern or "").strip()
    if not p:
        return None
    if len(p) > MAX_PATTERN_LEN:
        raise ImportError_(f"自定义规则太长（最多 {MAX_PATTERN_LEN} 个字符）", 422)
    try:
        return re.compile(p)
    except re.error as e:
        raise ImportError_(f"自定义规则不是合法的正则表达式：{e}", 422) from e


def _match_volume(line: str) -> tuple[str, str] | None:
    m = _VOL.match(line)
    if m:
        return re.sub(r"\s+", "", m.group(1)), (m.group(3) or "").strip()
    m = _VOL_ALT.match(line)
    if m:
        return m.group(1), (m.group(2) or "").strip()
    return None


def _match_chapter(line: str) -> tuple[str, str, int | None] | None:
    """→ (章号部分, 标题部分, 解析出的章号)。"""
    m = _CH_MAIN.match(line)
    if m:
        return re.sub(r"\s+", "", m.group(1)), (m.group(3) or "").strip(), cn2int(m.group(2))
    m = _CH_EN.match(line)
    if m:
        return m.group(1), (m.group(3) or "").strip(), int(m.group(2))
    m = _CH_SPECIAL.match(line)
    if m:
        return m.group(1), (m.group(2) or "").strip(), None
    return None


def _scan(lines: list[str], mode: str, custom: re.Pattern[str] | None, headings: set[str]) -> list[dict[str, Any]]:
    """按某一种规则找出所有标题行 → [{line, kind: chapter|volume, label, title, num}]。"""
    marks: list[dict[str, Any]] = []
    for i, raw in enumerate(lines):
        line = raw.strip().strip("\u3000")
        if not line or len(line) > TITLE_MAX + 12:
            continue
        v = _match_volume(line) if mode != "custom" else None
        if v and mode in ("auto", "headings", "numbered"):
            marks.append({"line": i, "kind": "volume", "label": v[0], "title": v[1], "num": None})
            continue
        if mode == "custom":
            if custom is not None and custom.search(line):
                marks.append({"line": i, "kind": "chapter", "label": "", "title": line, "num": None})
        elif mode == "auto":
            c = _match_chapter(line)
            if c:
                marks.append({"line": i, "kind": "chapter", "label": c[0], "title": c[1], "num": c[2]})
        elif mode == "headings":
            md = _MD_HEAD.match(line)
            t = md.group(2).strip() if md else line
            if line in headings or (md and t in headings):
                marks.append({"line": i, "kind": "chapter", "label": "", "title": t, "num": None})
        elif mode == "numbered":
            m = _NUMBERED.match(line)
            if m and not re.search(r"[。！？；，,]$", line):
                marks.append({"line": i, "kind": "chapter", "label": "", "title": m.group(2).strip(), "num": int(m.group(1))})
    return marks


def _numbered_ok(marks: list[dict[str, Any]]) -> bool:
    nums = [m["num"] for m in marks if m["kind"] == "chapter"]
    if len(nums) < 3:
        return False
    steps = sum(1 for a, b in zip(nums, nums[1:]) if b == a + 1)
    return steps >= 0.8 * (len(nums) - 1)


def split_text(text: str, pattern: str | None = None, headings: list[str] | None = None,
               split_volumes: bool = True) -> dict[str, Any]:
    """→ {chapters:[{title, raw_title, volume, num, content}], preface, rule}。没识别到标题时整段算一章。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    custom = compile_pattern(pattern)
    hs = {h.strip() for h in (headings or []) if h.strip()}
    marks: list[dict[str, Any]] = []
    rule = "none"
    tries = ["custom"] if custom is not None else ["auto", "headings", "numbered"]
    for mode in tries:
        if mode == "headings" and not hs:
            continue
        ms = _scan(lines, mode, custom, hs)
        n_ch = sum(1 for m in ms if m["kind"] == "chapter")
        if mode == "numbered" and not _numbered_ok(ms):
            continue
        if n_ch >= 2 or (mode == "custom" and n_ch >= 1) or (mode == "auto" and n_ch >= 1 and len(tries) == 1):
            marks, rule = ms, mode
            break
        if mode == "auto" and n_ch == 1:  # 只有一个标题也比整段强，但继续看其它规则能不能切出更多
            marks, rule = ms, mode
    if not split_volumes:
        marks = [m for m in marks if m["kind"] != "volume"]
    chapter_marks = [m for m in marks if m["kind"] == "chapter"]
    if not chapter_marks:
        body = text.strip()
        return {"chapters": [{"title": "", "raw_title": "全文", "volume": "", "num": None, "content": body}] if body else [],
                "preface": "", "rule": "none", "volume_intros": {}}
    preface = "\n".join(lines[:marks[0]["line"]]).strip()
    out: list[dict[str, Any]] = []
    intros: dict[str, str] = {}
    volume = ""
    for k, m in enumerate(marks):
        end = marks[k + 1]["line"] if k + 1 < len(marks) else len(lines)
        body = "\n".join(lines[m["line"] + 1:end]).strip()
        if m["kind"] == "volume":
            volume = " ".join(x for x in (m["label"], m["title"]) if x).strip()
            if body:  # 卷标题后、第一章前的文字（卷首语）不算正文，记作卷概要
                intros[volume] = body[:800]
            continue
        raw_title = " ".join(x for x in (m["label"], m["title"]) if x).strip() or lines[m["line"]].strip()
        out.append({"title": (m["title"] or ("" if m["label"] else raw_title))[:60], "raw_title": raw_title[:80],
                    "volume": volume, "num": m["num"], "content": body})
    return {"chapters": out, "preface": preface, "rule": rule, "volume_intros": intros}


def flag_chapters(chapters: list[dict[str, Any]]) -> list[list[str]]:
    """切分体检：空章、过短、过长（可能漏切）、标题重复、正文重复、章号不连续。"""
    words = [count_words(c.get("content") or "") for c in chapters]
    nonzero = [w for w in words if w > 0]
    med = statistics.median(nonzero) if nonzero else 0
    flags: list[list[str]] = []
    seen_title: dict[str, int] = {}
    seen_hash: dict[str, int] = {}
    prev_num: int | None = None
    for i, c in enumerate(chapters):
        f: list[str] = []
        w = words[i]
        if w < 20:
            f.append("empty")
        elif med and w < med * 0.25 and w < 500:
            f.append("short")
        if med and w > med * 3.5 and w > 8000:
            f.append("long")
        t = (c.get("raw_title") or c.get("title") or "").strip()
        if t and t != "全文":
            key = re.sub(r"\s+", "", t)
            if key in seen_title:
                f.append("dup_title")
            seen_title.setdefault(key, i)
        body = re.sub(r"\s+", "", c.get("content") or "")
        if len(body) >= 50:
            h = hashlib.md5(body.encode("utf-8")).hexdigest()
            if h in seen_hash:
                f.append("dup_content")
            seen_hash.setdefault(h, i)
        num = c.get("num")
        if isinstance(num, int):
            if prev_num is not None and num != prev_num + 1 and num != 1:
                f.append("gap")
            prev_num = num
        flags.append(f)
    return flags


def guess_title(text: str, filename: str | None, preface: str = "") -> str:
    head = (preface or text[:2000]).replace("\r", "")
    m = _TITLE_KV.search(head) or _TITLE_LINE.search(head)
    if m:
        return m.group(1).strip().strip("《》")[:40]
    if filename:
        stem = PurePath(filename).stem
        stem = re.sub(r"[\(（\[【].*?[\)）\]】]", "", stem)
        stem = re.sub(r"\s*(作者|by)[:：\s].*$", "", stem, flags=re.I).strip().strip("《》 ")
        if stem:
            return stem[:40]
    for line in head.split("\n")[:5]:
        line = line.strip()
        if 2 <= len(line) <= 20 and not _match_chapter(line):
            return line.strip("《》")[:40]
    return ""


def guess_premise(preface: str) -> str:
    """书名/作者行之后的前言文字（常见的「简介：…」）当作核心设定的候选。"""
    if not preface:
        return ""
    m = _INTRO_KV.search(preface)
    body = preface[m.end():] if m else preface
    body = re.sub(r"^[ \t\u3000]*(?:简介|内容简介|作品简介)[:：]\s*", "", body, flags=re.M)
    keep = [ln.strip() for ln in body.split("\n") if ln.strip() and not _TITLE_KV.match(ln) and not _TITLE_LINE.match(ln)
            and not re.match(r"^(作者|标签|类型|状态|字数)[:：]", ln.strip())]
    return "\n".join(keep)[:600]


def preview(data: bytes | None = None, text: str | None = None, filename: str | None = None,
            pattern: str | None = None, split_volumes: bool = True) -> dict[str, Any]:
    src = read_input(data, text, filename)
    sp = split_text(src["text"], pattern, src["headings"], split_volumes)
    chs = sp["chapters"]
    if len(chs) > MAX_CHAPTERS:
        raise ImportError_(f"切出了 {len(chs)} 章，超过单次导入上限 {MAX_CHAPTERS} 章；请检查切章规则或分几次导入", 422)
    flags = flag_chapters(chs)
    words = [count_words(c["content"]) for c in chs]
    warnings: list[str] = []
    if sp["rule"] == "none":
        warnings.append("没认出章节标题，整篇算一章；可以填自定义规则重新切，或在预览里手动拆分")
    elif sp["rule"] == "numbered":
        warnings.append("没有「第X章」格式的标题，按行首序号切的章，请核对")
    elif sp["rule"] == "headings":
        warnings.append("按文档里的标题样式（或 Markdown 标题）切的章，请核对")
    n_flag = sum(1 for f in flags if f)
    if n_flag:
        warnings.append(f"{n_flag} 章需要留意（空章、过长过短、重复或章号不连续），已在预览里标出")
    volumes: list[str] = []
    for c in chs:
        if c["volume"] and c["volume"] not in volumes:
            volumes.append(c["volume"])
    title = guess_title(src["text"], filename, sp["preface"])
    pre_lines = [ln.strip() for ln in sp["preface"].split("\n") if ln.strip()]
    if pre_lines and pre_lines[0] in set(src["headings"]) and len(pre_lines[0]) <= 40:  # 文档开头的标题样式段落就是书名
        title = pre_lines[0].strip("《》")
    premise = "\n".join(ln for ln in guess_premise(sp["preface"]).split("\n") if ln.strip().strip("《》") != title)
    return {
        "title_guess": title,
        "premise_guess": premise,
        "format": src["format"], "encoding": src["encoding"], "filename": filename or "",
        "rule": sp["rule"], "pattern": (pattern or "").strip(),
        "preface": sp["preface"][:2000],
        "total_words": sum(words),
        "median_words": int(statistics.median([w for w in words if w] or [0])),
        "volumes": volumes,
        "volume_intros": sp["volume_intros"],
        "chapters": [{"index": i, "title": c["title"], "raw_title": c["raw_title"], "volume": c["volume"], "num": c["num"],
                      "words": words[i], "content": c["content"], "flags": flags[i]} for i, c in enumerate(chs)],
        "flag_labels": FLAG_LABEL,
        "warnings": warnings,
    }


# ------------------------------------------------------------------ 大纲文本

_OL_CH = re.compile(rf"^[【\[]?\s*第\s*({_NUM})\s*[章回节]\s*[】\]]?[ \t\u3000]*[:：、.．\-—·]*[ \t\u3000]*(.*)$")
_OL_NUM = re.compile(r"^(\d{1,4})[ \t\u3000]*[.、．:：)）][ \t\u3000]*(.+)$")
_OL_ARC = re.compile(r"^(?:[【\[]\s*)?(?:第\s*[0-9一二三四五六七八九十百]+\s*[弧幕篇单元]|(?:剧情)?[弧幕篇]\s*[0-9一二三四五六七八九十]+)\s*[】\]]?[ \t\u3000]*[:：、.．\-—·]*[ \t\u3000]*(.*)$")


def parse_outline(text: str) -> dict[str, Any]:
    """程序解析大纲文本 → {book:{summary}, volumes:[{title, summary, arcs:[{title, summary, chapters:[{number, title, goal}]}]}]}。
    识别「第X卷」「第X章」「1. / 1、」「第X幕/弧/篇」；标题行下面的文字算这一节的概要。模型结构化前的骨架，也是演示模式的结果。"""
    lines = [ln.rstrip() for ln in (text or "").replace("\r", "").split("\n")]
    has_ch = any(_OL_CH.match(ln.strip()) for ln in lines)
    book_lines: list[str] = []
    vols: list[dict[str, Any]] = []
    cur_vol: dict[str, Any] | None = None
    cur_arc: dict[str, Any] | None = None
    cur: dict[str, Any] | None = None  # 最近一个节点（收集其下的文字）
    seq = 0

    def vol() -> dict[str, Any]:
        nonlocal cur_vol
        if cur_vol is None:
            cur_vol = {"title": "", "summary": "", "arcs": []}
            vols.append(cur_vol)
        return cur_vol

    def arc() -> dict[str, Any]:
        nonlocal cur_arc
        if cur_arc is None:
            cur_arc = {"title": "", "summary": "", "chapters": []}
            vol()["arcs"].append(cur_arc)
        return cur_arc

    for raw in lines:
        line = raw.strip().strip("\u3000").lstrip("#").strip()
        if not line:
            continue
        v = _match_volume(line)
        if v and len(line) <= TITLE_MAX:
            cur_vol = {"title": " ".join(x for x in v if x), "summary": "", "arcs": []}
            vols.append(cur_vol)
            cur_arc, cur = None, cur_vol
            continue
        am = _OL_ARC.match(line)
        if am and len(line) <= TITLE_MAX:
            cur_arc = {"title": line[:60], "summary": "", "chapters": []}
            vol()["arcs"].append(cur_arc)
            cur = cur_arc
            continue
        cm = _OL_CH.match(line)
        nm = None if has_ch else _OL_NUM.match(line)
        if cm or nm:
            m = cm or nm
            assert m is not None
            num = cn2int(m.group(1)) if cm else int(m.group(1))
            seq = num if num else seq + 1
            rest = (m.group(2) or "").strip()
            title, goal = rest, ""
            for sep in ("：", ":", "——", " - ", "。"):
                if sep in rest:
                    a, b = rest.split(sep, 1)
                    if 0 < len(a.strip()) <= 20:
                        title, goal = a.strip(), b.strip()
                        break
            if len(title) > 24 and not goal:
                title, goal = "", rest
            ch = {"number": seq, "title": title[:30], "goal": goal[:300]}
            arc()["chapters"].append(ch)
            cur = ch
            continue
        if cur is None:
            book_lines.append(line)
        elif "number" in cur:
            cur["goal"] = (cur["goal"] + ("；" if cur["goal"] else "") + line)[:600]
        else:
            cur["summary"] = (cur["summary"] + ("\n" if cur["summary"] else "") + line)[:800]
    for v in vols:
        for i, a in enumerate(v["arcs"], 1):
            if not a["title"]:
                nums = [c["number"] for c in a["chapters"]]
                a["title"] = f"第{min(nums)}–{max(nums)}章" if nums else f"第{i}段"
    n_ch = sum(len(a["chapters"]) for v in vols for a in v["arcs"])
    return {"book": {"summary": "\n".join(book_lines)[:1500]}, "volumes": vols, "chapters": n_ch}
