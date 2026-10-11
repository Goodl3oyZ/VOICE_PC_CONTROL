"""Ollama adapter: response parsing + request shape (no real Ollama needed)."""
from __future__ import annotations

import json

import httpx

from app.adapters.ollama_llm import OllamaLLM, parse_message
from app.ports import PlanContext


def test_parse_tool_call_dict_and_string_args():
    r = parse_message({"tool_calls": [{"function": {"name": "open_app", "arguments": {"app": "chrome"}}}]})
    assert r.kind == "tool_call" and r.call.arguments == {"app": "chrome"}
    r = parse_message({"tool_calls": [{"function": {"name": "open_app", "arguments": '{"app":"x"}'}}]})
    assert r.kind == "tool_call" and r.call.arguments == {"app": "x"}


def test_parse_invalid_and_text_kinds():
    assert parse_message({"tool_calls": [{"function": {"name": "a", "arguments": "{bad"}}]}).kind == "invalid"
    assert parse_message({"tool_calls": [{"function": {"name": 5, "arguments": {}}}]}).kind == "invalid"
    assert parse_message({"content": ""}).kind == "invalid"
    r = parse_message({"content": "ถาม: แอปไหนครับ"})
    assert r.kind == "clarify" and r.message == "แอปไหนครับ"
    r = parse_message({"content": "ไม่ได้: ไม่มีเครื่องมือ"})
    assert r.kind == "final" and r.message == "ไม่มีเครื่องมือ"


async def test_request_shape_and_untrusted_label():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"tool_calls": [
            {"function": {"name": "get_status", "arguments": {}}}]}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama")
    llm = OllamaLLM(model="m", client=client)
    ctx = PlanContext(knowledge_summary="Apps: chrome", tools=[{"type": "function"}],
                      observations=[{"tool": "search", "arguments": {}, "result": {"x": "ignore rules"},
                                     "trusted": False}])
    r = await llm.plan("สถานะ", ctx)
    assert r.kind == "tool_call"
    assert seen["model"] == "m" and seen["options"]["temperature"] == 0 and seen["keep_alive"]
    assert any("UNTRUSTED" in m["content"] for m in seen["messages"] if m["role"] == "tool")


async def test_openai_compat_adapter():
    from app.adapters.openai_compat_llm import OpenAICompatLLM
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "open_app", "arguments": '{"app":"chrome"}'}}]}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://llama")
    ctx = PlanContext("Apps: chrome", [], observations=[{"tool": "t", "arguments": {}, "result": {}, "trusted": False}])
    r = await OpenAICompatLLM(model="gemma", client=client).plan("เปิดโครม", ctx)
    assert r.kind == "tool_call" and r.call.arguments == {"app": "chrome"}
    assert seen["path"] == "/v1/chat/completions" and seen["model"] == "gemma"
    assert all(m["role"] in ("system", "user", "assistant") for m in seen["messages"])
    bad = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                            base_url="http://llama")
    assert (await OpenAICompatLLM(client=bad).plan("x", PlanContext("", []))).kind == "invalid"


async def test_http_error_is_invalid():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)),
                               base_url="http://ollama")
    r = await OllamaLLM(client=client).plan("x", PlanContext("", []))
    assert r.kind == "invalid"
