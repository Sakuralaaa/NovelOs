"""LLM 网关：OpenAI 兼容 chat completions + images，多渠道按角色路由、重试与切换、token 记录。

- 角色：planner / writer / reviewer / embedding / image
- 路由值："channel_id:model" 或 null
- 没有任何启用的渠道 → mock 模式（确定性假数据，见 app.llm.mock）
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlmodel import Session, select

from app.config import get_settings
from app.db import kv_get, session_scope
from app.llm import mock
from app.llm.crypto import decrypt
from app.models.tables import Channel, TokenUsage

log = logging.getLogger("novelos.llm")

ROLES = ("planner", "writer", "reviewer", "embedding", "image")
ROUTING_KEY = "routing"

# 任务默认走哪个角色
TASK_ROLE: dict[str, str] = {
    "ideation": "planner",
    "bible": "planner",
    "outline": "planner",
    "expand": "planner",
    "scene_plan": "planner",
    "package": "planner",
    "style_extract": "reviewer",
    "writing_scene": "writer",
    "humanize": "writer",
    "thicken": "writer",
    "summary": "reviewer",
    "review": "reviewer",
}


class LLMError(RuntimeError):
    pass


@dataclass
class Target:
    channel_id: int
    name: str
    base_url: str
    api_key: str
    model: str


def get_routing(s: Session) -> dict[str, str | None]:
    raw = kv_get(s, ROUTING_KEY, {}) or {}
    return {r: raw.get(r) for r in ROLES}


def enabled_channels(s: Session) -> list[Channel]:
    return list(s.exec(select(Channel).where(Channel.enabled == True).order_by(Channel.id)))  # noqa: E712


def is_mock_mode(s: Session) -> bool:
    return len(enabled_channels(s)) == 0


def _parse_route(v: str | None) -> tuple[int, str] | None:
    if not v or ":" not in v:
        return None
    cid, model = v.split(":", 1)
    try:
        return int(cid), model
    except ValueError:
        return None


def resolve_targets(s: Session, role: str) -> list[Target]:
    """返回该角色的候选目标：路由指定的在前，其他启用渠道在后（用于失败切换）。

    image / embedding 角色未配置路由时返回空列表（调用方走本地/mock 实现），
    因为多数文本渠道并不支持生图。
    """
    chans = enabled_channels(s)
    if not chans:
        return []
    routing = get_routing(s)
    route = _parse_route(routing.get(role))
    if route is None and role in ("image", "embedding"):
        return []
    out: list[Target] = []
    primary_model: str | None = None
    by_id = {c.id: c for c in chans}
    if route and route[0] in by_id:
        c = by_id[route[0]]
        primary_model = route[1]
        out.append(Target(c.id or 0, c.name, c.base_url, decrypt(c.api_key_enc), route[1]))
    for c in chans:
        if any(t.channel_id == c.id for t in out):
            continue
        if not c.models:
            continue
        model = primary_model if primary_model in c.models else c.models[0]
        out.append(Target(c.id or 0, c.name, c.base_url, decrypt(c.api_key_enc), model))
    return out


def _url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def _record_usage(target: Target, role: str, task: str, usage: dict[str, Any] | None) -> None:
    if not usage:
        return
    try:
        with session_scope() as s:
            s.add(
                TokenUsage(
                    channel_id=target.channel_id,
                    model=target.model,
                    role=role,
                    task=task,
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                )
            )
            s.commit()
    except Exception:  # pragma: no cover - 记账失败不影响主流程
        log.exception("记录 token 用量失败")


def extract_json(text: str) -> Any:
    """从模型输出中取出 JSON（容忍 ```json 代码块与前后废话）。"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        a, b = t.find(open_c), t.rfind(close_c)
        if a != -1 and b > a:
            try:
                return json.loads(t[a : b + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("模型输出不是合法 JSON")


class LLMGateway:
    def __init__(self) -> None:
        self.settings = get_settings()

    # ---------- chat ----------
    def chat(
        self,
        task: str,
        messages: list[dict[str, str]],
        meta: dict[str, Any] | None = None,
        role: str | None = None,
        temperature: float = 0.8,
        max_tokens: int | None = None,
    ) -> str:
        role = role or TASK_ROLE.get(task, "planner")
        with session_scope() as s:
            targets = resolve_targets(s, role)
        if not targets:
            return mock.complete(task, messages, meta or {})
        errors: list[str] = []
        for t in targets:
            for attempt in range(self.settings.llm_retries + 1):
                try:
                    return self._chat_once(t, role, task, messages, temperature, max_tokens)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{t.name}/{t.model} 第{attempt + 1}次：{e}")
                    log.warning("LLM 调用失败 %s", errors[-1])
                    time.sleep(min(2.0, 0.5 * (attempt + 1)))
        raise LLMError("所有渠道均失败：" + "；".join(errors[-4:]))

    def _chat_once(
        self,
        t: Target,
        role: str,
        task: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        body: dict[str, Any] = {"model": t.model, "messages": messages, "temperature": temperature}
        if max_tokens:
            body["max_tokens"] = max_tokens
        with httpx.Client(timeout=self.settings.llm_timeout) as c:
            r = c.post(
                _url(t.base_url, "/chat/completions"),
                headers={"Authorization": f"Bearer {t.api_key}"},
                json=body,
            )
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        _record_usage(t, role, task, data.get("usage"))
        content = data["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise LLMError("模型返回空内容")
        return str(content)

    def chat_json(
        self,
        task: str,
        system: str,
        user: str,
        meta: dict[str, Any] | None = None,
        role: str | None = None,
        temperature: float = 0.7,
    ) -> Any:
        """要求 JSON 输出；解析失败时追加提醒重试 1 次。"""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        out = self.chat(task, messages, meta=meta, role=role, temperature=temperature)
        try:
            return extract_json(out)
        except ValueError:
            messages += [
                {"role": "assistant", "content": out[:4000]},
                {"role": "user", "content": "上面的输出不是合法 JSON。请只输出符合要求的 JSON，不要任何其他文字。"},
            ]
            out = self.chat(task, messages, meta=meta, role=role, temperature=0.3)
            return extract_json(out)

    # ---------- images ----------
    def images(self, prompt: str, n: int = 1) -> list[bytes] | None:
        """返回图片字节列表；未配置 image 路由（或 mock 模式）返回 None，由调用方本地生成。"""
        with session_scope() as s:
            targets = resolve_targets(s, "image")
        if not targets:
            return None
        errors: list[str] = []
        for t in targets:
            for attempt in range(self.settings.llm_retries + 1):
                try:
                    return self._images_once(t, prompt, n)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{t.name}/{t.model}：{e}")
                    time.sleep(0.5 * (attempt + 1))
        raise LLMError("生图失败：" + "；".join(errors[-3:]))

    def _images_once(self, t: Target, prompt: str, n: int) -> list[bytes]:
        body = {"model": t.model, "prompt": prompt, "n": n, "size": self.settings.image_size}
        with httpx.Client(timeout=max(self.settings.llm_timeout, 180)) as c:
            r = c.post(
                _url(t.base_url, "/images/generations"),
                headers={"Authorization": f"Bearer {t.api_key}"},
                json=body,
            )
            if r.status_code >= 400:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            _record_usage(t, "image", "cover", data.get("usage"))
            out: list[bytes] = []
            for item in data.get("data", []):
                if item.get("b64_json"):
                    out.append(base64.b64decode(item["b64_json"]))
                elif item.get("url"):
                    img = c.get(item["url"])
                    img.raise_for_status()
                    out.append(img.content)
        if not out:
            raise LLMError("生图接口未返回图片")
        return out

    # ---------- channel test ----------
    @staticmethod
    def test_channel(base_url: str, api_key: str, models: list[str], timeout: float = 20.0) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout) as c:
                headers = {"Authorization": f"Bearer {api_key}"}
                if models:
                    r = c.post(
                        _url(base_url, "/chat/completions"),
                        headers=headers,
                        json={"model": models[0], "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                    )
                else:
                    r = c.get(_url(base_url, "/models"), headers=headers)
            latency = int((time.perf_counter() - t0) * 1000)
            if r.status_code >= 400:
                return {"ok": False, "latency_ms": latency, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
            return {"ok": True, "latency_ms": latency}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "latency_ms": int((time.perf_counter() - t0) * 1000), "error": str(e)}


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
