"""联网搜索：模型列表解析、流式读取（无思维链/占位 reasoning/中途断开）。"""

from __future__ import annotations

import httpx

from app.llm import gateway as g


def test_parse_model_list_variants():
    assert g.parse_model_list({"data": [{"id": "b"}, {"id": "A"}, {"id": "b"}]}) == ["A", "b"]
    assert g.parse_model_list({"models": [{"name": "models/gemini-pro"}]}) == ["gemini-pro"]
    assert g.parse_model_list(["x", "y"]) == ["x", "y"]


def test_clean_search_text():
    assert g._clean_search_text("深度思考中\n\n结论") == "结论"
    assert g._clean_search_text("<think>abc</think>答案") == "答案"


def _target():
    return g.Target(1, "grok", "http://gw.test/v1", "k", "grok-4.20-multi-agent-0309")


def _patch_transport(monkeypatch, handler):
    monkeypatch.setattr(g, "_keepalive_transport", lambda: httpx.MockTransport(handler))


def test_search_stream_ignores_placeholder_reasoning(monkeypatch):
    sse = (
        ": keepalive\n\n"
        'data: {"choices":[{"delta":{"role":"assistant","reasoning_content":"深度思考中"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"1912 年"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"清帝退位。"}}],"usage":{"prompt_tokens":3,"completion_tokens":5}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(req.content)
        assert body["stream"] is True and "max_tokens" not in body
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode())

    _patch_transport(monkeypatch, handler)
    out = g.LLMGateway()._search_once(_target(), [{"role": "user", "content": "q"}])
    assert out == "1912 年清帝退位。"


def test_search_non_stream_fallback(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "深度思考中\n答案"}}]})

    _patch_transport(monkeypatch, handler)
    assert g.LLMGateway()._search_once(_target(), [{"role": "user", "content": "q"}]) == "答案"


def test_search_disconnect_keeps_partial(monkeypatch):
    long = "资料" * 60

    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield f'data: {{"choices":[{{"delta":{{"content":"{long}"}}}}]}}\n\n'.encode()
            raise httpx.RemoteProtocolError("peer closed")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Broken())

    _patch_transport(monkeypatch, handler)
    assert g.LLMGateway()._search_once(_target(), [{"role": "user", "content": "q"}]) == long


def test_protocol_parsing():
    from app.llm import protocols as p
    path, body = p.chat_request("anthropic", "claude", [{"role": "system", "content": "S"}, {"role": "user", "content": "hi"}], 0.8, None)
    assert path == "/messages" and body["system"] == "S" and body["max_tokens"] == 8192
    path, body = p.chat_request("gemini", "models/gemini-2.5-pro", [{"role": "user", "content": "hi"}], None, 10, want_image=True)
    assert path == "/models/gemini-2.5-pro:generateContent" and body["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
    text, usage, imgs = p.parse_chat("gemini", {"candidates": [{"content": {"parts": [{"text": "想", "thought": True}, {"text": "答"}, {"inlineData": {"data": "aGk="}}]}}]})
    assert text == "答" and imgs == [b"hi"]
    text, _, imgs = p.parse_chat("openai", {"choices": [{"message": {"content": "![c](data:image/png;base64,aGk=)"}}]})
    assert imgs == [b"hi"]
    text, usage, _ = p.parse_chat("responses", {"output": [{"type": "message", "content": [{"type": "output_text", "text": "R"}]}], "usage": {"input_tokens": 2, "output_tokens": 3}})
    assert text == "R" and usage == {"prompt_tokens": 2, "completion_tokens": 3}


def test_delete_endpoints(client):
    r = client.post("/api/ideas/clear")
    assert r.status_code == 200
    assert client.delete("/api/ideas/999999").status_code == 404
    assert client.delete("/api/chapters/999999").status_code == 404
    assert client.delete("/api/outline/999999").status_code == 404
    rt = client.get("/api/settings/routing").json()
    assert "search" in rt and rt["image_mode"] in ("images", "chat")
