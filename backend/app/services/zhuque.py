"""v0.9.1 朱雀 AIGC 文本检测（腾讯 EdgeOne Makers 内置模型 @makers/zhuque-text）。

只做检测，给作者自查与合规参考：不会根据检测分自动改写，写章流程默认也不调用（会耗用户的免费额度）。

接口：POST {base_url}/v1/providers/zhuque-text/classify，Authorization: Bearer <key>，body {"text", "is_merge"}。
响应：softmax_confidence（0–1，越大越像 AI）、ratio_confidence（疑似风险占比）、labels_ratio {"0":人工,"1":AI,"2":疑似AI}、
segment_labels [{text,label,conf,order,position}]、usage / makers_models_usage.total_tokens。

长文按段落切块（每块 ≤ zhuque_chunk_chars，默认 8000 字），逐块调用后按字数加权合并 softmax / ratio / labels_ratio，
segment 的位置换算回全文偏移 [start, end)。
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from typing import Any

import httpx
from sqlmodel import Session

from app.config import get_settings
from app.db import kv_get, kv_set, session_scope
from app.llm.crypto import decrypt, encrypt
from app.models.tables import Chapter, utcnow
from app.services.common import Conflict, NotFound

log = logging.getLogger("novelos.zhuque")

SETTINGS_KEY = "zhuque_settings"
USAGE_KEY = "zhuque_usage"
PATH = "/v1/providers/zhuque-text/classify"
LABELS = {"0": "human", "1": "ai", "2": "suspect"}
LEVEL_MID, LEVEL_HIGH = 0.5, 0.85
MAX_TEXT = 200_000


class ZhuqueError(RuntimeError):
    pass


# ------------------------------------------------------------------ 设置（密钥加密存库，对外只给尾号）

def _raw(s: Session) -> dict[str, Any]:
    v = kv_get(s, SETTINGS_KEY, {}) or {}
    return v if isinstance(v, dict) else {}


def get_key(s: Session) -> str:
    enc = _raw(s).get("api_key_enc") or ""
    return decrypt(enc) if enc else ""


def base_url(s: Session) -> str:
    return (_raw(s).get("base_url") or get_settings().zhuque_default_base_url).rstrip("/")


def auto_check(s: Session) -> bool:
    return bool(_raw(s).get("auto_check"))


def settings_out(s: Session) -> dict[str, Any]:
    try:
        key = get_key(s)
        tail = key[-4:] if key else ""
    except ValueError:  # 主密钥变了，解不开
        key, tail = "x", "????"
    usage = kv_get(s, USAGE_KEY, {}) or {}
    return {"zhuque_configured": bool(key), "zhuque_key_tail": tail, "zhuque_base_url": base_url(s),
            "zhuque_auto_check": auto_check(s),
            "zhuque_usage": {"calls": int(usage.get("calls") or 0), "tokens": int(usage.get("tokens") or 0)}}


def update_settings(s: Session, api_key: str | None = None, base: str | None = None, auto: bool | None = None) -> dict[str, Any]:
    """局部更新：传 None 的项不改；api_key 传空串表示清除密钥；base 传空串恢复默认地址。"""
    cur = dict(_raw(s))
    if api_key is not None:
        cur["api_key_enc"] = encrypt(api_key.strip()) if api_key.strip() else ""
    if base is not None:
        b = base.strip().rstrip("/")
        if b and not re.match(r"^https?://[^\s/]+", b):
            raise ValueError("朱雀接口地址要以 http:// 或 https:// 开头")
        cur["base_url"] = b
    if auto is not None:
        cur["auto_check"] = bool(auto)
    kv_set(s, SETTINGS_KEY, cur)
    return settings_out(s)


def require_configured() -> None:
    with session_scope() as s:
        if not settings_out(s)["zhuque_configured"]:
            raise Conflict("还没有配置朱雀检测密钥：请到「设置 → 朱雀 AIGC 检测」填写 EdgeOne Makers 的 API Key")


def _add_usage(tokens: int, calls: int) -> None:
    with session_scope() as s:
        u = dict(kv_get(s, USAGE_KEY, {}) or {})
        u["calls"] = int(u.get("calls") or 0) + calls
        u["tokens"] = int(u.get("tokens") or 0) + tokens
        kv_set(s, USAGE_KEY, u)


# ------------------------------------------------------------------ 切块

def split_chunks(text: str, limit: int | None = None) -> list[tuple[int, str]]:
    """按段落切块，返回 [(全文起始偏移, 块文本)]；块是原文的连续切片（偏移可直接换算）。
    单段超过上限时按句号/硬切拆开。"""
    limit = max(200, int(limit or get_settings().zhuque_chunk_chars))
    if len(text) <= limit:
        return [(0, text)] if text.strip() else []
    # 段落边界：每个换行之后
    cuts = [m.end() for m in re.finditer(r"\n+", text)]
    bounds = [0, *[c for c in cuts if 0 < c < len(text)], len(text)]
    pieces: list[tuple[int, int]] = []
    for a, b in zip(bounds, bounds[1:]):
        while b - a > limit:  # 超长段：在上限内最后一个句末标点处切，没有就硬切
            seg = text[a:a + limit]
            k = max(seg.rfind(p) for p in "。！？!?；…")
            cut = a + (k + 1 if k > limit // 3 else limit)
            pieces.append((a, cut))
            a = cut
        if b > a:
            pieces.append((a, b))
    chunks: list[tuple[int, int]] = []
    for a, b in pieces:
        if chunks and b - chunks[-1][0] <= limit:
            chunks[-1] = (chunks[-1][0], b)
        else:
            chunks.append((a, b))
    return [(a, text[a:b]) for a, b in chunks if text[a:b].strip()]


# ------------------------------------------------------------------ 调用与合并

def _f(v: Any) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _label(v: Any) -> str:
    s = str(v).strip().lower()
    if s in LABELS:
        return LABELS[s]
    if s in ("human", "ai", "suspect"):
        return s
    return "suspect" if "疑似" in s else "ai" if "ai" in s or "机" in s else "human"


def _tokens(data: dict[str, Any]) -> int:
    for k in ("usage", "makers_models_usage"):
        u = data.get(k)
        if isinstance(u, dict) and u.get("total_tokens") is not None:
            try:
                return int(u["total_tokens"])
            except (TypeError, ValueError):
                pass
    return 0


def classify_chunk(client: httpx.Client, url: str, key: str, text: str, is_merge: bool) -> dict[str, Any]:
    try:
        r = client.post(url, json={"text": text, "is_merge": is_merge},
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    except httpx.TimeoutException as e:
        raise ZhuqueError(f"朱雀检测超时（{get_settings().zhuque_timeout:.0f} 秒没有返回），请稍后再试") from e
    except httpx.HTTPError as e:
        raise ZhuqueError(f"连不上朱雀检测接口：{e}") from e
    if r.status_code in (401, 403):
        raise ZhuqueError(f"朱雀检测密钥无效或没有权限（HTTP {r.status_code}）：请到「设置 → 朱雀 AIGC 检测」重新填写 EdgeOne Makers 的 API Key，"
                          "并确认该密钥已开通 @makers/zhuque-text")
    if r.status_code == 429:
        raise ZhuqueError("朱雀检测调用太频繁或额度已用完（HTTP 429），请稍后再试")
    if r.status_code != 200:
        raise ZhuqueError(f"朱雀检测接口返回 HTTP {r.status_code}：{r.text[:200]}")
    try:
        data = r.json()
    except ValueError as e:
        raise ZhuqueError("朱雀检测接口返回的不是 JSON") from e
    if isinstance(data, dict) and isinstance(data.get("data"), dict) and "softmax_confidence" not in data:
        data = {**data["data"], **{k: v for k, v in data.items() if k in ("usage", "makers_models_usage")}}
    if not isinstance(data, dict) or "softmax_confidence" not in data:
        msg = (data.get("message") or data.get("error") or data.get("status")) if isinstance(data, dict) else None
        raise ZhuqueError(f"朱雀检测没有返回结果：{str(msg or data)[:200]}")
    return data


def _segments(chunk: str, offset: int, raw: Any) -> list[dict[str, Any]]:
    """把块内 segment 换算成全文偏移。position 可能是起始下标、[start,end] 或 {start,end}；
    先在 position 附近按原文查找 segment 文本，找不到再信 position，都没有就顺序往后找。"""
    out: list[dict[str, Any]] = []
    cursor = 0
    rows = [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []
    rows.sort(key=lambda x: (int(x.get("order")) if str(x.get("order", "")).lstrip("-").isdigit() else 0))
    for x in rows:
        seg = str(x.get("text") or "")
        pos = x.get("position")
        start = end = None
        if isinstance(pos, (list, tuple)) and len(pos) >= 2:
            start, end = pos[0], pos[1]
        elif isinstance(pos, dict):
            start, end = pos.get("start"), pos.get("end")
        elif pos is not None:
            start = pos
        try:
            start = int(start) if start is not None else None
            end = int(end) if end is not None else None
        except (TypeError, ValueError):
            start = end = None
        if seg:
            hint = start if start is not None and 0 <= start <= len(chunk) else cursor
            i = chunk.find(seg, max(0, hint - 20))
            if i < 0:
                i = chunk.find(seg, cursor)
            if i < 0:
                i = chunk.find(seg)
            if i >= 0:
                start, end = i, i + len(seg)
        if start is None:
            continue
        if end is None or end <= start:
            end = start + max(1, len(seg))
        start, end = max(0, min(start, len(chunk))), max(0, min(end, len(chunk)))
        if end <= start:
            continue
        cursor = end
        out.append({"start": offset + start, "end": offset + end, "label": _label(x.get("label")), "conf": round(_f(x.get("conf")), 4)})
    return out


def level_of(softmax: float) -> str:
    return "high" if softmax >= LEVEL_HIGH else "mid" if softmax >= LEVEL_MID else "low"


def detect(text: str, is_merge: bool = True, progress=None) -> dict[str, Any]:
    """检测一段文字 → {softmax, ratio, labels_ratio:{human,ai,suspect}, level, ai_segment_ratio, suspect_segment_ratio,
    segments:[{start,end,label,conf}], tokens, chunks, chars, is_merge}。"""
    text = text or ""
    if not text.strip():
        raise ValueError("要检测的文字不能为空")
    if len(text) > MAX_TEXT:
        raise ValueError(f"文字太长（{len(text)} 字），一次最多检测 {MAX_TEXT} 字")
    with session_scope() as s:
        key = get_key(s)
        url = base_url(s) + PATH
    if not key:
        raise Conflict("还没有配置朱雀检测密钥：请到「设置 → 朱雀 AIGC 检测」填写 EdgeOne Makers 的 API Key")
    chunks = split_chunks(text)
    st = get_settings()
    total_w = 0
    acc_soft = acc_ratio = 0.0
    acc_labels = {"human": 0.0, "ai": 0.0, "suspect": 0.0}
    segments: list[dict[str, Any]] = []
    tokens = 0
    calls = 0
    try:
        with httpx.Client(timeout=st.zhuque_timeout) as c:
            for k, (off, chunk) in enumerate(chunks):
                if progress is not None:
                    progress(10 + int(80 * k / max(1, len(chunks))), f"朱雀检测第 {k + 1}/{len(chunks)} 块")
                data = classify_chunk(c, url, key, chunk, is_merge)
                calls += 1
                w = len(re.sub(r"\s", "", chunk)) or len(chunk)
                total_w += w
                acc_soft += _f(data.get("softmax_confidence")) * w
                acc_ratio += _f(data.get("ratio_confidence")) * w
                lr = data.get("labels_ratio") if isinstance(data.get("labels_ratio"), dict) else {}
                for raw_k, v in lr.items():
                    acc_labels[_label(raw_k)] += _f(v) * w
                segments.extend(_segments(chunk, off, data.get("segment_labels")))
                tokens += _tokens(data)
    finally:
        if calls:
            _add_usage(tokens, calls)
    total_w = total_w or 1
    softmax = round(acc_soft / total_w, 4)
    seg_chars = {"human": 0, "ai": 0, "suspect": 0}
    for sg in segments:
        seg_chars[sg["label"]] += sg["end"] - sg["start"]
    covered = sum(seg_chars.values())
    return {"softmax": softmax, "ratio": round(acc_ratio / total_w, 4),
            "labels_ratio": {k: round(v / total_w, 4) for k, v in acc_labels.items()}, "level": level_of(softmax),
            "ai_segment_ratio": round(seg_chars["ai"] / covered, 4) if covered else None,
            "suspect_segment_ratio": round(seg_chars["suspect"] / covered, 4) if covered else None,
            "segments": segments, "tokens": tokens, "chunks": len(chunks), "chars": len(text), "is_merge": is_merge}


# ------------------------------------------------------------------ 章节

def content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:16]


def check_chapter(chapter_id: int, book_id: int | None = None, progress=None, is_merge: bool = True) -> dict[str, Any]:
    """检测一章正文并存进 Chapter.aigc（默认 is_merge=true：相邻同类段合并；false 为逐段置信度）。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None or (book_id is not None and ch.book_id != book_id):
            raise NotFound("章节不存在")
        if not ch.content.strip():
            raise Conflict("章节正文为空")
        content = ch.content
    r = detect(content, is_merge, progress)
    aigc = {"checked_at": utcnow().isoformat().replace("+00:00", "Z"), "content_hash": content_hash(content), **r}
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        ch.aigc = aigc
        s.add(ch)
        s.commit()
    return {"chapter_id": chapter_id, "aigc": {**aigc, "stale": False}}


def maybe_auto_check(chapter_id: int) -> bool:
    """章节提交后：开启 zhuque_auto_check 且配置了密钥时，后台检测一次；失败只记日志，不影响提交。返回是否启动。"""
    try:
        with session_scope() as s:
            st = settings_out(s)
        if not (st["zhuque_auto_check"] and st["zhuque_configured"]):
            return False
    except Exception:  # noqa: BLE001
        return False

    def run() -> None:
        try:
            check_chapter(chapter_id)
        except Exception as e:  # noqa: BLE001
            log.warning("章节 %s 提交后的朱雀检测失败（不影响提交）：%s", chapter_id, e)

    threading.Thread(target=run, name=f"zhuque-auto-{chapter_id}", daemon=True).start()
    return True
