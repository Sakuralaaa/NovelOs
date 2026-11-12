"""包装：书名候选打分、简介、标签、封面提示词、封面生成、导出发布包。"""

from __future__ import annotations

import io
import re
import time
import zipfile
from typing import Any

from PIL import Image

from app.config import get_settings
from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Book, Package, utcnow
from app.services import common
from app.services.cover import compose_from_image, placeholder_cover
from app.skills.loader import render, system_prompt

# 书名四维打分（各 25 分）：思路参考 aby-aby111/fanqie-short-story.skill（GPL，仅借思路），代码自写
_NUM = re.compile(r"[0-9０-９一二三四五六七八九十百千万两]")
EMOTION_WORDS = ["杀疯", "疯", "爽", "哭", "跪", "宠", "虐", "怒", "恨", "爱", "甜", "炸", "狂", "崩", "慌", "悔", "撩",
                 "离谱", "震惊", "打脸", "逆袭", "复仇", "无敌", "求", "狠", "怕", "惊", "不服"]
IDENTITY_WORDS = ["我", "她", "他", "前夫", "夫人", "老婆", "老公", "千金", "少爷", "王爷", "皇后", "贵妃", "太子", "总裁",
                  "师尊", "师父", "徒弟", "赘婿", "神医", "大佬", "债主", "家主", "宗主", "嫡女", "庶女", "女帝", "爸", "妈",
                  "儿子", "女儿", "哥", "姐", "弟", "妹"]


def score_title(title: str) -> dict[str, int]:
    n = len(re.sub(r"[\s，,：:！!？?。]", "", title))
    length = 25 if 8 <= n <= 12 else 12 if 6 <= n <= 15 else 0
    number = 25 if _NUM.search(title) else 0
    emotion = 25 if any(w in title for w in EMOTION_WORDS) else 0
    identity = 25 if any(w in title for w in IDENTITY_WORDS) else 0
    return {"length": length, "number": number, "emotion": emotion, "identity": identity,
            "total": length + number + emotion + identity}


def get_or_create_package(s: Any, book_id: int) -> Package:
    pkg = s.get(Package, book_id)
    if pkg is None:
        pkg = Package(book_id=book_id)
        s.add(pkg)
        s.flush()
    return pkg


def generate_package(book_id: int, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        book = common.get_book(s, book_id)
        meta = common.kit_meta(s, book)
        recent = common.committed_chapters(s, book_id)[-5:]
        user = render("package", book_context=common.book_context(s, book),
                      recent="\n".join(f"第{c.number}章：{c.summary}" for c in recent) or "（尚未写正文）")
    ctx.progress(20, "生成书名、简介、标签与封面提示词")
    data = get_gateway().chat_json("package", system_prompt("package"), user, meta=meta)
    if not isinstance(data, dict):
        raise ValueError("包装结果不是 JSON 对象")
    raw_titles = [str(t.get("title") if isinstance(t, dict) else t) for t in (data.get("titles") or [])]
    titles = [{"title": t, "score": score_title(t)["total"]} for t in dict.fromkeys(x.strip() for x in raw_titles if x.strip())]
    titles.sort(key=lambda x: -x["score"])
    with session_scope() as s:
        book = common.get_book(s, book_id)
        pkg = get_or_create_package(s, book_id)
        pkg.titles = titles[:12]
        pkg.blurb = str(data.get("blurb", ""))
        pkg.tags = [str(t) for t in (data.get("tags") or [])][:6]
        pkg.cover_prompt = str(data.get("cover_prompt", ""))
        s.add(pkg)
        if book.status in ("idea", "bible", "outline", "writing"):
            book.status = "packaging"
        book.updated_at = utcnow()
        s.add(book)
        s.commit()
    return {"titles": len(titles)}


def cover_design_prompt(title: str, genre: str, scene: str) -> str:
    """模型写字模式：把书名交给生图模型做成封面主视觉，画面描述由用户写。"""
    scene = re.sub(r"[^，,。；;（）()\n]*(不要|不展示|不出现|不带)[^，,。；;\n]*(文字|字样|标识|书名)[^，,。；;\n]*[，,。；;]?", "", scene).strip()
    return "\n".join([
        "你是专业的网文封面设计师，请设计一张适合番茄小说书架的封面，竖版 3:4。",
        f"书名：「{title}」。书名是封面的视觉主体：大号粗体艺术字，字体有冲击力，可按语义断成 2–3 行错落排布，"
        "可加描边、金属或火焰等质感，和画面融为一体；每个字必须准确，不能错字、漏字、多字。",
        f"题材：{genre}。",
        f"画面：{scene or genre + '题材的主角与标志性场景'}",
        "书名以外不要出现其他文字、水印、平台标志；四周留安全边距，字不要贴边。",
    ])


def to_png(raw: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def generate_covers(book_id: int, prompt: str | None, n: int, ctx: JobContext, title_mode: str = "model") -> dict[str, Any]:
    n = max(1, min(4, n))
    with session_scope() as s:
        book = common.get_book(s, book_id)
        pkg = get_or_create_package(s, book_id)
        s.commit()
        title, genre = book.title, book.genre
        scene = (prompt or pkg.cover_prompt or "").strip()
    if title_mode == "model":
        final = cover_design_prompt(title, genre, scene)
    else:
        final = scene or f"{genre}网文封面，竖版 3:4，上方留出书名空间，不要文字，不要水印"
    ctx.progress(10, "生成封面")
    raws = get_gateway().images(final, n)
    out_dir = get_settings().media_dir / "books" / str(book_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time() * 1000)
    urls: list[str] = []
    for i in range(n):
        ctx.progress(20 + 70 * i // n, f"处理第 {i + 1}/{n} 张")
        if raws and title_mode == "model":
            data = to_png(raws[i % len(raws)])
        elif raws:
            data = compose_from_image(raws[i % len(raws)], title, genre)
        else:
            data = placeholder_cover(title, genre, stamp + i)
        name = f"cover_{stamp}_{i + 1}.png"
        (out_dir / name).write_bytes(data)
        urls.append(f"/media/books/{book_id}/{name}")
    with session_scope() as s:
        book = common.get_book(s, book_id)
        pkg = get_or_create_package(s, book_id)
        pkg.covers = [*(pkg.covers or []), *urls]
        if not pkg.chosen_cover:
            pkg.chosen_cover = urls[0]
            book.cover_url = urls[0]
        pkg.cover_prompt = pkg.cover_prompt or scene
        s.add(pkg)
        s.add(book)
        s.commit()
    return {"covers": urls, "source": "image" if raws else "local"}


def cover_file(url: str | None) -> bytes | None:
    if not url or not url.startswith("/media/"):
        return None
    p = get_settings().media_dir / url[len("/media/") :]
    return p.read_bytes() if p.exists() else None


AI_NOTICE = """# AI 申报提示（发布前必读）

本发布包由 NovelOS 辅助生成，正文含 AI 生成合成内容。发布到番茄小说前请注意：

1. **如实勾选 AI 申报**：番茄发布章节时会询问“是否使用 AI”，请如实勾选。未如实申报的章节可能无法通过审核。
2. **法规要求**：《人工智能生成合成内容标识办法》（2025-09-01 施行）第十条要求，用户发布 AI 生成合成内容时应主动声明并使用平台提供的标识功能，不得删除、篡改或隐匿标识。
3. **人工改写把关**：请逐章通读、改写、核对设定，确保内容是你认可的作品。平台持续整治“滥用 AI 批量生成、严重缺乏原创性”的内容（拒签、限流、下架乃至封号）。
4. **控制更新节奏**：遵守平台单账号、单本书每日/每月的发文与字数限制，不要批量开书。
5. **手动上架**：NovelOS 不会自动登录或发布到作者后台，请在番茄作家后台或作家助手 App 中手动创建作品与章节。

本提示不构成法律意见；以平台最新规则为准。
"""


def build_export(book_id: int) -> tuple[str, bytes]:
    with session_scope() as s:
        book: Book = common.get_book(s, book_id)
        pkg = s.get(Package, book_id)
        chapters = common.committed_chapters(s, book_id)
        cards_ = common.cards(s, book_id)
        nodes = common.outline_nodes(s, book_id)
        stats = common.book_stats(s, book_id)

        md: list[str] = [f"# 建书资料：{book.title}", ""]
        md += ["## 基本信息", f"- 书名：{book.title}", f"- 频道：{common.GENDER_LABEL.get(book.gender, book.gender)}",
               f"- 分类：{book.genre}", f"- 一句话卖点：{book.tagline}",
               f"- 已提交章节：{stats['chapters']} 章，{stats['words']} 字", ""]
        if pkg:
            md += ["## 作品简介", pkg.blurb or "（未生成）", "", "## 标签", "、".join(pkg.tags) or "（未生成）", ""]
            if pkg.titles:
                md += ["## 书名候选（程序评分，满分 100）"] + [f"- {t['title']}（{t['score']}）" for t in pkg.titles] + [""]
            if pkg.cover_prompt:
                md += ["## 封面提示词", pkg.cover_prompt, ""]
        chars = [c for c in cards_ if c.type == "character"]
        if chars:
            md += ["## 主要人物"] + [f"- **{c.name}**：{c.summary}" for c in chars] + [""]
        vols = sorted([n for n in nodes if n.level == "volume"], key=lambda n: n.order)
        if vols:
            md += ["## 大纲概览"]
            for v in vols:
                md.append(f"- {v.title}：{v.summary}")
            md.append("")
        if chapters:
            md += ["## 章节目录"] + [f"- 第{c.number}章 {c.title}（{c.words} 字）" for c in chapters] + [""]

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("建书资料.md", "\n".join(md))
            for c in chapters:
                safe = re.sub(r'[\\/:*?"<>|\s]+', "_", c.title)[:30]
                z.writestr(f"chapters/{c.number:03d}_{safe}.txt", f"第{c.number}章 {c.title}\n\n{c.content.strip()}\n")
            cover = cover_file(pkg.chosen_cover if pkg else None) or cover_file(book.cover_url)
            if cover is None:
                cover = placeholder_cover(book.title, book.genre, 0)
            z.writestr("cover.png", cover)
            z.writestr("AI申报提示.md", AI_NOTICE)
        return book.title, buf.getvalue()
