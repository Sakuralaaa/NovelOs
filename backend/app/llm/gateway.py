"""LLM 网关：OpenAI 兼容 chat completions + images，多渠道按角色路由、重试与切换、token 记录。

- 角色：planner / writer / reviewer / search / embedding / image / agent（每本书的专属 Agent，未配置时用 planner 的路由）
- 路由值："channel_id:model" 或 null
- 没有任何启用的渠道 → mock 模式（确定性假数据，见 app.llm.mock）
"""

from __future__ import annotations

import base64
import json
import logging
import re
import socket
import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlmodel import Session, select

from app.config import get_settings
from app.db import kv_get, session_scope
from app.llm import mock
from app.llm import protocols as proto
from app.llm import trace
from app.llm.crypto import decrypt
from app.models.tables import Channel, TokenUsage

log = logging.getLogger("novelos.llm")

ROLES = ("planner", "writer", "reviewer", "search", "embedding", "image", "agent")
# 只走路由指定模型、不向其它渠道切换的角色（普通文本模型做不了这些事）
STRICT_ROLES = ("search", "embedding", "image")
ROUTING_KEY = "routing"
IMAGE_MODE_KEY = "image_mode"  # images：/images/generations；chat：对话接口出图

# 任务默认走哪个角色
TASK_ROLE: dict[str, str] = {
    "ideation": "planner",
    "idea_score": "reviewer",
    "idea_revise": "planner",
    "idea_field": "planner",
    "bible": "planner",
    "card_suggest": "planner",
    "outline": "planner",
    "expand": "planner",
    "scene_plan": "planner",
    "package": "planner",
    "cover_prompt": "planner",
    "style_extract": "reviewer",
    "writing_scene": "writer",
    "humanize": "writer",
    "thicken": "writer",
    "summary": "reviewer",
    "review": "reviewer",
    "book_revise": "planner",
    "bible_propose": "planner",
    "outline_node": "planner",
    "outline_sync": "planner",
    "chapter_rewrite": "writer",
    "foreshadow_plan": "planner",
    "teardown": "planner",
    "teardown_deep": "reviewer",
    "reskin": "planner",
    "agent": "agent",
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
    api_format: str = "openai"


def get_image_mode(s: Session) -> str:
    v = kv_get(s, IMAGE_MODE_KEY, "images")
    return v if v in ("images", "chat") else "images"


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
    if route is None and role in STRICT_ROLES:
        return []
    out: list[Target] = []
    primary_model: str | None = None
    by_id = {c.id: c for c in chans}
    if route and route[0] in by_id:
        c = by_id[route[0]]
        primary_model = route[1]
        out.append(Target(c.id or 0, c.name, c.base_url, decrypt(c.api_key_enc), route[1], c.api_format or "openai"))
    if role == "search":
        return out
    for c in chans:
        if any(t.channel_id == c.id for t in out):
            continue
        if not c.models:
            continue
        model = primary_model if primary_model in c.models else c.models[0]
        out.append(Target(c.id or 0, c.name, c.base_url, decrypt(c.api_key_enc), model, c.api_format or "openai"))
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


def _search_params(t: Target) -> dict[str, Any]:
    """部分服务商需要显式打开联网：通义千问 enable_search，智谱 web_search 工具。

    Perplexity sonar、OpenRouter 的 `:online` 模型、gpt-4o-search-preview 等本身就联网，不用额外参数。
    """
    base = t.base_url.lower()
    if "dashscope" in base:
        return {"enable_search": True}
    if "bigmodel.cn" in base:
        return {"tools": [{"type": "web_search", "web_search": {"enable": True}}]}
    return {}


def _not_retryable(e: Exception) -> bool:
    return bool(re.match(r"HTTP (400|401|403|404|422)\b", str(e)))


def _friendly(e: Exception) -> str:
    msg = str(e)
    if "model_not_found" in msg or "unknown provider for model" in msg or "model not found" in msg.lower():
        return "模型名不存在，请在渠道里用「拉取模型」选择接口返回的模型 ID（不是页面上显示的名称）"
    if re.match(r"HTTP (401|403)\b", msg):
        return "API Key 无效或没有该模型的权限"
    return msg


_THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.S)


def _clean_search_text(text: str) -> str:
    """去掉混进正文的思维链标签和网关占位文字。"""
    text = _THINK_RE.sub("", text)
    text = re.sub(r"^\s*(深度思考中[.。…]*\s*)+", "", text)
    return text.strip()


def _keepalive_transport() -> httpx.HTTPTransport:
    opts: list[tuple[int, int, int]] = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    for name, val in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 15), ("TCP_KEEPCNT", 8)):
        if hasattr(socket, name):
            opts.append((socket.IPPROTO_TCP, getattr(socket, name), val))
    return httpx.HTTPTransport(socket_options=opts, retries=1)


def _download(c: httpx.Client, u: str) -> bytes:
    r = c.get(u)
    r.raise_for_status()
    return r.content


def parse_model_list(data: Any) -> list[str]:
    """兼容 OpenAI {data:[{id}]}、{models:[{name|id}]} 与纯数组。"""
    items: Any = data
    if isinstance(data, dict):
        items = data.get("data") or data.get("models") or []
    out: list[str] = []
    for it in items if isinstance(items, list) else []:
        mid = it if isinstance(it, str) else (it.get("id") or it.get("name") or it.get("model")) if isinstance(it, dict) else None
        if mid:
            mid = str(mid).removeprefix("models/")
            if mid not in out:
                out.append(mid)
    return sorted(out, key=str.lower)


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


def route_target(s: Session, route: str) -> Target:
    """用户手动指定的「渠道:模型」，不做切换。"""
    r = _parse_route(route)
    c = s.get(Channel, r[0]) if r else None
    if r is None or c is None or not c.enabled:
        raise LLMError("选的模型不可用，渠道可能已删除或停用")
    return Target(c.id or 0, c.name, c.base_url, decrypt(c.api_key_enc), r[1], c.api_format or "openai")


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
        route: str | None = None,
    ) -> str:
        role = role or TASK_ROLE.get(task, "planner")
        with session_scope() as s:
            targets = [route_target(s, route)] if route else resolve_targets(s, role)
        if not targets:
            started = time.time()
            out = mock.complete(task, messages, meta or {})
            trace.record(task=task, role=role, model="mock", channel="mock", messages=messages, output=out,
                         started=started, temperature=temperature)
            return out
        errors: list[str] = []
        for t in targets:
            for attempt in range(self.settings.llm_retries + 1):
                try:
                    return self._chat_once(t, role, task, messages, temperature, max_tokens)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{t.name}/{t.model}：{_friendly(e)}")
                    log.warning("LLM 调用失败 %s", errors[-1])
                    if _not_retryable(e):  # 模型名错、key 无效这类请求错误，重试也没用，直接换下一个渠道
                        break
                    time.sleep(min(2.0, 0.5 * (attempt + 1)))
        raise LLMError("所有渠道均失败：" + "；".join(dict.fromkeys(errors[-4:])))

    def _post_chat(
        self, t: Target, messages: list[dict[str, str]], temperature: float | None, max_tokens: int | None,
        want_image: bool = False, timeout: float | None = None,
    ) -> dict[str, Any]:
        path, body = proto.chat_request(t.api_format, t.model, messages, temperature, max_tokens, want_image)
        with httpx.Client(timeout=timeout or self.settings.llm_timeout, transport=_keepalive_transport()) as c:
            r = c.post(proto.url(t.base_url, path), headers=proto.headers(t.api_format, t.api_key), json=body)
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise LLMError("返回的不是 JSON，检查 Base URL 和接口格式是否匹配") from e

    def _chat_once(
        self,
        t: Target,
        role: str,
        task: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        started = time.time()
        try:
            data = self._post_chat(t, messages, temperature, max_tokens)
            content, usage, _ = proto.parse_chat(t.api_format, data)
        except Exception as e:
            trace.record(task=task, role=role, model=t.model, channel=t.name, messages=messages, output="",
                         started=started, error=_friendly(e), temperature=temperature)
            raise
        _record_usage(t, role, task, usage)
        trace.record(task=task, role=role, model=t.model, channel=t.name, messages=messages, output=content,
                     started=started, usage=usage, temperature=temperature,
                     error=None if content.strip() else "模型返回空内容")
        if not content.strip():
            raise LLMError("模型返回空内容")
        return content

    def chat_json(
        self,
        task: str,
        system: str,
        user: str,
        meta: dict[str, Any] | None = None,
        role: str | None = None,
        temperature: float = 0.7,
        route: str | None = None,
    ) -> Any:
        """要求 JSON 输出；解析失败时追加提醒重试 1 次。"""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        out = self.chat(task, messages, meta=meta, role=role, temperature=temperature, route=route)
        try:
            return extract_json(out)
        except ValueError:
            messages += [
                {"role": "assistant", "content": out[:4000]},
                {"role": "user", "content": "上面的输出不是合法 JSON。请只输出符合要求的 JSON，不要任何其他文字。"},
            ]
            out = self.chat(task, messages, meta=meta, role=role, temperature=0.3, route=route)
            return extract_json(out)

    # ---------- agent：function calling ----------
    def chat_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        meta: dict[str, Any] | None = None,
        route: str | None = None,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        """一步 Agent 推理：返回 {content, tool_calls:[{id, name, arguments(dict)}]}。

        OpenAI 兼容格式走原生 function calling；其它格式（anthropic / gemini / responses）退化为文本协议：
        把工具说明写进系统提示，让模型输出 ```tool {...}``` 代码块，再由程序解析。没有任何渠道时走 mock 规则脚本。
        """
        with session_scope() as s:
            if route:
                targets = [route_target(s, route)]
            else:
                routing = get_routing(s)
                targets = resolve_targets(s, "agent" if _parse_route(routing.get("agent")) else "planner")
        if not targets:
            return mock.agent_step(messages, tools, meta or {})
        errors: list[str] = []
        for t in targets:
            for attempt in range(self.settings.llm_retries + 1):
                try:
                    if t.api_format == "openai":
                        return self._tools_once(t, messages, tools, temperature)
                    return self._tools_text(t, messages, tools, temperature)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{t.name}/{t.model}：{_friendly(e)}")
                    log.warning("Agent 调用失败 %s", errors[-1])
                    if _not_retryable(e):
                        break
                    time.sleep(min(2.0, 0.5 * (attempt + 1)))
        raise LLMError("所有渠道均失败：" + "；".join(dict.fromkeys(errors[-4:])))

    def _tools_once(self, t: Target, messages: list[dict[str, Any]], tools: list[dict[str, Any]], temperature: float) -> dict[str, Any]:
        started = time.time()
        body: dict[str, Any] = {"model": t.model, "messages": proto.openai_tool_messages(messages), "tools": tools,
                                "tool_choice": "auto", "temperature": temperature}
        with httpx.Client(timeout=self.settings.llm_timeout, transport=_keepalive_transport()) as c:
            r = c.post(proto.url(t.base_url, "/chat/completions"), headers=proto.headers("openai", t.api_key), json=body)
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
        except ValueError as e:
            raise LLMError("返回的不是 JSON，检查 Base URL 和接口格式是否匹配") from e
        out = proto.parse_tool_response(data)
        usage = out.pop("usage", None)
        _record_usage(t, "agent", "agent", usage)
        trace.record(task="agent", role="agent", model=t.model, channel=t.name, messages=messages,
                     output={"content": out["content"], "tool_calls": out["tool_calls"]}, started=started,
                     usage=usage, temperature=temperature)
        if not out["content"].strip() and not out["tool_calls"]:
            raise LLMError("模型返回空内容")
        return out

    def _tools_text(self, t: Target, messages: list[dict[str, Any]], tools: list[dict[str, Any]], temperature: float) -> dict[str, Any]:
        started = time.time()
        msgs = proto.text_tool_messages(messages, tools)
        data = self._post_chat(t, msgs, temperature, None)
        content, usage, _ = proto.parse_chat(t.api_format, data)
        _record_usage(t, "agent", "agent", usage)
        trace.record(task="agent", role="agent", model=t.model, channel=t.name, messages=msgs, output=content,
                     started=started, usage=usage, temperature=temperature)
        out = proto.parse_text_tool_calls(content, {f["function"]["name"] for f in tools})
        if not out["content"].strip() and not out["tool_calls"]:
            raise LLMError("模型返回空内容")
        return out

    # ---------- search ----------
    def has_search(self) -> bool:
        with session_scope() as s:
            return bool(resolve_targets(s, "search"))

    def search(self, query: str, context: str = "") -> str | None:
        """用路由里的联网搜索模型查一个问题；未配置返回 None。失败抛 LLMError。"""
        system = (
            "你是小说创作的资料核查员，可以联网搜索。针对问题检索可靠来源，用中文给出简洁、可直接用于写作的事实，"
            "250 字以内，末尾列出 1~3 个来源链接。查不到或说法有争议时直说，不要编造。"
        )
        user = f"问题：{query}" + (f"\n\n写作背景（仅供理解问题）：{context[:600]}" if context else "")
        with session_scope() as s:
            targets = resolve_targets(s, "search")
        if not targets:
            return None
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        errors: list[str] = []
        t = targets[0]
        for attempt in range(2):
            try:
                return self._search_once(t, msgs)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{t.name}/{t.model} 第{attempt + 1}次：{e}")
                log.warning("联网搜索失败 %s", errors[-1])
                time.sleep(1.0 + attempt)
        raise LLMError("联网搜索失败：" + "；".join(errors[-2:]))

    def _search_once(self, t: Target, messages: list[dict[str, str]]) -> str:
        """流式读取搜索结果。

        多 agent 搜索模型可能几分钟不吐正文、也不给思维链（网关只补一个占位 reasoning），
        非流式请求在这段静默里容易被中间层掐断，所以：流式 + 只收 content + 长空闲超时 + TCP keepalive；
        中途断开但已收到足够正文时直接用已收到的部分。
        """
        limit = max(self.settings.search_timeout, self.settings.llm_timeout)
        if t.api_format != "openai":
            data = self._post_chat(t, messages, None, None, timeout=limit)
            text, usage, _ = proto.parse_chat(t.api_format, data)
            _record_usage(t, "search", "search", usage)
            text = _clean_search_text(text)
            if not text:
                raise LLMError("搜索模型返回空内容")
            return text
        body: dict[str, Any] = {"model": t.model, "messages": messages, "stream": True}
        body.update(_search_params(t))
        timeout = httpx.Timeout(connect=20.0, read=limit, write=30.0, pool=20.0)
        deadline = time.monotonic() + limit
        parts: list[str] = []
        usage: dict[str, Any] | None = None
        with httpx.Client(timeout=timeout, transport=_keepalive_transport()) as c:
            try:
                with c.stream(
                    "POST", _url(t.base_url, "/chat/completions"),
                    headers={"Authorization": f"Bearer {t.api_key}", "Accept": "text/event-stream"}, json=body,
                ) as r:
                    if r.status_code >= 400:
                        raise LLMError(f"HTTP {r.status_code}: {r.read().decode(errors='replace')[:200]}")
                    if "text/event-stream" not in r.headers.get("content-type", ""):
                        data = json.loads(r.read() or b"{}")
                        _record_usage(t, "search", "search", data.get("usage"))
                        msg = (data.get("choices") or [{}])[0].get("message") or {}
                        return _clean_search_text(str(msg.get("content") or ""))
                    for line in r.iter_lines():
                        if time.monotonic() > deadline:
                            raise LLMError(f"超过 {int(limit)} 秒未完成")
                        if not line or line.startswith(":") or not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            ev = json.loads(payload)
                        except ValueError:
                            continue
                        if ev.get("error"):
                            raise LLMError(str(ev["error"])[:200])
                        usage = ev.get("usage") or usage
                        for ch in ev.get("choices") or []:
                            piece = (ch.get("delta") or ch.get("message") or {}).get("content")
                            if piece:
                                parts.append(str(piece))
            except (httpx.TransportError, LLMError) as e:
                got = _clean_search_text("".join(parts))
                if len(got) >= 80:
                    log.warning("联网搜索中途断开，使用已收到的 %d 字：%s", len(got), e)
                    return got
                raise LLMError(str(e) or type(e).__name__) from e
        _record_usage(t, "search", "search", usage)
        text = _clean_search_text("".join(parts))
        if not text:
            raise LLMError("搜索模型返回空内容")
        return text

    # ---------- images ----------
    def images(self, prompt: str, n: int = 1) -> list[bytes] | None:
        """返回图片字节列表；未配置 image 路由（或 mock 模式）返回 None，由调用方本地生成。"""
        with session_scope() as s:
            targets = resolve_targets(s, "image")
            mode = get_image_mode(s)
        if not targets:
            return None
        errors: list[str] = []
        for t in targets[:1]:
            for attempt in range(self.settings.llm_retries + 1):
                try:
                    if mode == "chat" or t.api_format in ("anthropic", "gemini"):
                        return self._images_via_chat(t, prompt, n)
                    return self._images_once(t, prompt, n)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{t.name}/{t.model}：{_friendly(e)}")
                    if _not_retryable(e):
                        break
                    time.sleep(0.5 * (attempt + 1))
        raise LLMError("生图失败：" + "；".join(dict.fromkeys(errors[-3:])))

    def _images_once(self, t: Target, prompt: str, n: int) -> list[bytes]:
        body = {"model": t.model, "prompt": prompt, "n": n, "size": self.settings.image_size}
        with httpx.Client(timeout=max(self.settings.llm_timeout, 300), follow_redirects=True) as c:
            r = c.post(proto.url(t.base_url, "/images/generations"), headers=proto.headers("openai", t.api_key), json=body)
            if r.status_code >= 400:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            _record_usage(t, "image", "cover", data.get("usage"))
            out: list[bytes] = []
            for item in data.get("data", []):
                if item.get("b64_json"):
                    out.append(base64.b64decode(item["b64_json"]))
                elif item.get("url"):
                    out.append(_download(c, item["url"]))
        if not out:
            raise LLMError("生图接口未返回图片")
        return out

    def _images_via_chat(self, t: Target, prompt: str, n: int) -> list[bytes]:
        """对话接口出图：一次请求一张，从返回里取 base64 / data URL / 图片链接。"""
        w, _, h = self.settings.image_size.partition("x")
        ask = f"{prompt}\n\n直接生成图片，竖版，尺寸约 {w}×{h}，只返回图片，不要附带说明文字。"
        out: list[bytes] = []
        with httpx.Client(timeout=60, follow_redirects=True) as dl:
            for _ in range(max(1, n)):
                data = self._post_chat(t, [{"role": "user", "content": ask}], None, None, want_image=True,
                                       timeout=max(self.settings.llm_timeout, 300))
                _, usage, imgs = proto.parse_chat(t.api_format, data)
                _record_usage(t, "image", "cover", usage)
                for im in imgs:
                    out.append(im if isinstance(im, bytes) else _download(dl, im))
                    break
        if not out:
            raise LLMError("对话接口没有返回图片，确认该模型支持出图，或改用生图接口")
        return out

    # ---------- model list ----------
    @staticmethod
    def list_models(base_url: str, api_key: str, api_format: str = "openai", timeout: float = 20.0) -> list[str]:
        path, params = proto.models_request(api_format)
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as c:
                r = c.get(proto.url(base_url, path), headers=proto.headers(api_format, api_key), params=params)
        except httpx.HTTPError as e:
            raise LLMError(f"连接失败：{e}") from e
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
        except ValueError as e:
            raise LLMError("返回的不是 JSON，检查 Base URL 和接口格式") from e
        models = parse_model_list(data)
        if not models:
            raise LLMError("接口没有返回任何模型")
        return models

    # ---------- channel test ----------
    @staticmethod
    def test_channel(base_url: str, api_key: str, models: list[str], api_format: str = "openai",
                     timeout: float = 30.0) -> dict[str, Any]:
        t0 = time.perf_counter()
        ms = lambda: int((time.perf_counter() - t0) * 1000)  # noqa: E731
        try:
            if not models:
                LLMGateway.list_models(base_url, api_key, api_format, timeout)
                return {"ok": True, "latency_ms": ms()}
            t = Target(0, "test", base_url, api_key, models[0], api_format)
            LLMGateway()._post_chat(t, [{"role": "user", "content": "ping"}], None, 16, timeout=timeout)
            return {"ok": True, "latency_ms": ms()}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "latency_ms": ms(), "error": _friendly(e)}


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
