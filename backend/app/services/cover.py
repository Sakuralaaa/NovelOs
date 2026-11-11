"""封面：image 路由出图后本地叠加书名排版；mock / 未配置生图时用 Pillow 生成渐变封面（3:4，600x800）。"""

from __future__ import annotations

import hashlib
import io
import logging
import math
import random
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.config import get_settings

log = logging.getLogger("novelos.cover")

W, H = 600, 800

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]

PALETTES: list[tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = [
    ((12, 18, 40), (88, 28, 92), (255, 196, 92)),     # 夜紫金
    ((8, 32, 48), (18, 110, 130), (180, 240, 255)),   # 深海青
    ((40, 6, 10), (150, 20, 30), (255, 210, 160)),    # 赤血
    ((20, 24, 20), (60, 100, 60), (230, 240, 200)),   # 墨竹
    ((30, 10, 40), (220, 90, 130), (255, 230, 240)),  # 女频粉
    ((10, 10, 14), (70, 70, 90), (235, 235, 245)),    # 冷灰
]


@lru_cache
def cjk_font_path() -> str | None:
    s = get_settings()
    for p in [s.font_path, *FONT_CANDIDATES]:
        if p and Path(p).exists():
            return p
    log.warning("未找到中文字体，封面书名将无法排版。请安装 fonts-wqy-microhei 或设置 NOVELOS_FONT_PATH")
    return None


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    p = cjk_font_path()
    if p:
        return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _gradient(palette_idx: int, rng: random.Random) -> Image.Image:
    top, bottom, accent = PALETTES[palette_idx % len(PALETTES)]
    sw, sh = W // 4, H // 4
    small = Image.new("RGB", (sw, sh))
    px = small.load()
    assert px is not None
    cx, cy = rng.uniform(0.25, 0.75) * sw, rng.uniform(0.45, 0.7) * sh
    radius = rng.uniform(0.45, 0.7) * sh
    for y in range(sh):
        base = _lerp(top, bottom, y / sh)
        for x in range(sw):
            d = math.hypot(x - cx, y - cy) / radius
            glow = max(0.0, 1 - d) ** 2 * 0.55
            px[x, y] = _lerp(base, accent, glow)
    img = small.resize((W, H), Image.BICUBIC)
    # 光束与粒子
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    for _ in range(rng.randint(3, 6)):
        x0 = rng.randint(-200, W)
        od.polygon([(x0, 0), (x0 + rng.randint(40, 120), 0), (x0 + rng.randint(200, 420), H), (x0 + rng.randint(120, 260), H)],
                   fill=(*accent, rng.randint(12, 28)))
    for _ in range(160):
        x, y, r = rng.randint(0, W), rng.randint(0, H), rng.choice([1, 1, 1, 2, 3])
        od.ellipse((x - r, y - r, x + r, y + r), fill=(*accent, rng.randint(40, 160)))
    over = over.filter(ImageFilter.GaussianBlur(1.2))
    img = Image.alpha_composite(img.convert("RGBA"), over)
    # 底部山形剪影
    sil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sil)
    pts = [(0, H)]
    for i in range(0, W + 40, 40):
        pts.append((i, int(H * 0.78 + rng.randint(-40, 30))))
    pts.append((W, H))
    sd.polygon(pts, fill=(*_lerp(top, (0, 0, 0), 0.5), 235))
    return Image.alpha_composite(img, sil)


def _wrap(title: str, per_line: int) -> list[str]:
    t = re.sub(r"[：:，,！!？?、]", "\n", title)
    lines: list[str] = []
    for seg in t.split("\n"):
        seg = seg.strip(" 。")
        if not seg:
            continue
        parts = math.ceil(len(seg) / per_line)
        size = math.ceil(len(seg) / parts)  # 均分，避免“七字 + 两字”的孤行
        lines.extend(seg[i : i + size] for i in range(0, len(seg), size))
    return lines[:4]


def overlay_title(img: Image.Image, title: str, subtitle: str, accent: tuple[int, int, int] = (255, 220, 150)) -> Image.Image:
    img = img.convert("RGBA")
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(int(H * 0.45)):
        sd.line([(0, y), (W, y)], fill=(0, 0, 0, int(150 * (1 - y / (H * 0.45)))))
    img = Image.alpha_composite(img, shade)
    d = ImageDraw.Draw(img)
    if cjk_font_path() is None:
        d.rectangle((40, 40, W - 40, H - 40), outline=(*accent, 200), width=3)
        d.text((60, H - 90), "NovelOS", font=_font(24), fill=(255, 255, 255, 220))
        return img.convert("RGB")
    lines = _wrap(title, 7)
    size = 76 if max(len(x) for x in lines) <= 5 else 64 if max(len(x) for x in lines) <= 7 else 52
    f = _font(size)
    while size > 30 and max(d.textbbox((0, 0), ln, font=f)[2] for ln in lines) > W - 70:
        size -= 4
        f = _font(size)
    y = 70
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=f)
        w = bbox[2] - bbox[0]
        x = (W - w) // 2
        d.text((x + 4, y + 5), line, font=f, fill=(0, 0, 0, 170))
        d.text((x, y), line, font=f, fill=(255, 250, 240), stroke_width=3, stroke_fill=(*accent,))
        y += size + 14
    if subtitle:
        fs = _font(24)
        bbox = d.textbbox((0, 0), subtitle, font=fs)
        x = (W - (bbox[2] - bbox[0])) // 2
        d.rounded_rectangle((x - 16, H - 92, x + (bbox[2] - bbox[0]) + 16, H - 52), radius=18, fill=(0, 0, 0, 120),
                            outline=(*accent, 200), width=2)
        d.text((x, H - 88), subtitle, font=fs, fill=(255, 255, 255))
    return img.convert("RGB")


def placeholder_cover(title: str, subtitle: str, variant: int) -> bytes:
    seed = int(hashlib.sha256(f"{title}|{variant}".encode("utf-8")).hexdigest()[:12], 16)
    rng = random.Random(seed)
    pal = (seed + variant) % len(PALETTES)
    img = _gradient(pal, rng)
    out = overlay_title(img, title, subtitle, PALETTES[pal][2])
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def compose_from_image(raw: bytes, title: str, subtitle: str) -> bytes:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = img.size
    target = 3 / 4
    if w / h > target:
        nw = int(h * target)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / target)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    img = img.resize((W, H), Image.LANCZOS)
    out = overlay_title(img, title, subtitle)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()
