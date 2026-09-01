"""端到端集成测试：本地 mock OpenAI 兼容上游 -> 网关 -> 客户端（含流式）。

启动一个真实 HTTP mock 上游，把网关的通用兼容通道指向它，
用 TestClient 调网关，验证非流式与流式全链路。
"""
from __future__ import annotations

import json
import threading

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from gateway.config import Config
from server import create_app

# ---------- mock 上游 ----------
_mock_app = FastAPI()


@_mock_app.post("/v1/chat/completions")
def _chat(req: dict):
    model = req.get("model", "mock")
    if req.get("stream", False):
        chunks = [
            {"id": "m1", "object": "chat.completion.chunk", "model": model,
             "choices": [{"index": 0, "delta": {"content": "mock "}, "finish_reason": None}]},
            {"id": "m1", "object": "chat.completion.chunk", "model": model,
             "choices": [{"index": 0, "delta": {"content": "回复"}, "finish_reason": None}]},
            {"id": "m1", "object": "chat.completion.chunk", "model": model,
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        body = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
        return StreamingResponse(iter([body + "data: [DONE]\n\n"]), media_type="text/event-stream")
    return JSONResponse({
        "id": "m1", "object": "chat.completion", "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "mock 回复"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
    })


# DeepSeek 网页版逆向端点（路径同真实 chat.deepseek.com）
@_mock_app.post("/api/v0/chat/completions")
def _deepseek_chat(req: dict):
    model = req.get("model", "deepseek_chat")
    if req.get("stream", False):
        chunks = [
            {"id": "ds1", "object": "chat.completion.chunk", "model": model,
             "choices": [{"index": 0, "delta": {"content": "DS "}, "finish_reason": None}]},
            {"id": "ds1", "object": "chat.completion.chunk", "model": model,
             "choices": [{"index": 0, "delta": {"content": "回复"}, "finish_reason": None}]},
            {"id": "ds1", "object": "chat.completion.chunk", "model": model,
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        body = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
        return StreamingResponse(iter([body + "data: [DONE]\n\n"]), media_type="text/event-stream")
    return JSONResponse({
        "id": "ds1", "object": "chat.completion", "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "DS 回复"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
    })


# 通义千问网页版逆向端点（mock qianwen.biz.aliyun.com /dialog/conversation）
@_mock_app.post("/dialog/conversation")
def _qwen_chat(req: Request):
    cookie_hdr = req.headers.get("cookie", "")
    assert "tongyi_sso_ticket" in cookie_hdr or "login_aliyunid_ticket" in cookie_hdr, "missing ticket"
    events = [
        {"sessionId": "sess123", "msgId": "msg1",
         "contents": [{"contentType": "text", "role": "assistant", "content": "千问"}]},
        {"sessionId": "sess123", "msgId": "msg2",
         "contents": [{"contentType": "text", "role": "assistant", "content": "千问 回复"}]},
    ]
    body = "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"
    return StreamingResponse(iter([body]), media_type="text/event-stream")


@pytest.fixture(scope="module")
def mock_server_url():
    port = 9099
    config = uvicorn.Config(_mock_app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # 等端口就绪
    import time
    import socket
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _make_gateway(mock_url: str) -> TestClient:
    cfg = Config(
        host="127.0.0.1", port=5005, authorization=["srv-key"],
        doubao_cookies=[], doubao_session_ids=[],
        ark_api_key="",
        compat_base_url=f"{mock_url}/v1", compat_api_key="k", compat_model="mock",
    )
    return TestClient(create_app(cfg))


def test_compat_non_stream(mock_server_url):
    client = _make_gateway(mock_server_url)
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer srv-key"},
        json={"model": "compat-mock", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "mock 回复"
    assert data["usage"]["total_tokens"] == 8


def test_compat_stream(mock_server_url):
    client = _make_gateway(mock_server_url)
    with client.stream(
        "POST", "/v1/chat/completions",
        headers={"Authorization": "Bearer srv-key"},
        json={"model": "compat-mock", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "[DONE]" in body
    contents = []
    for line in body.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            ev = json.loads(line[6:])
            for choice in ev.get("choices", []):
                d = choice.get("delta", {})
                if d.get("content"):
                    contents.append(d["content"])
    assert "".join(contents) == "mock 回复"


def test_compat_models(mock_server_url):
    client = _make_gateway(mock_server_url)
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()["data"]]
    assert any("compat-mock" in i for i in ids)


# ---------- DeepSeek 网页版 / 通义千问 ----------
def _make_deepseek_gateway(mock_url: str) -> TestClient:
    cfg = Config(
        host="127.0.0.1", port=5005, authorization=["srv-key"],
        doubao_cookies=[], doubao_session_ids=[],
        ark_api_key="", compat_base_url="", compat_api_key="", compat_model="",
        deepseek_token="ds-token", deepseek_web_base=mock_url,
    )
    return TestClient(create_app(cfg))


def test_deepseek_web_non_stream(mock_server_url):
    client = _make_deepseek_gateway(mock_server_url)
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer srv-key"},
        json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "DS 回复"


def test_deepseek_web_stream(mock_server_url):
    client = _make_deepseek_gateway(mock_server_url)
    with client.stream(
        "POST", "/v1/chat/completions",
        headers={"Authorization": "Bearer srv-key"},
        json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "[DONE]" in body
    contents = []
    for line in body.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            ev = json.loads(line[6:])
            for choice in ev.get("choices", []):
                d = choice.get("delta", {})
                if d.get("content"):
                    contents.append(d["content"])
    assert "".join(contents) == "DS 回复"


def test_qwen_non_stream(mock_server_url):
    cfg = Config(
        host="127.0.0.1", port=5005, authorization=["srv-key"],
        doubao_cookies=[], doubao_session_ids=[],
        ark_api_key="", compat_base_url="", compat_api_key="", compat_model="",
        qwen_api_key="q-key", qwen_base_url=f"{mock_server_url}/v1",
    )
    client = TestClient(create_app(cfg))
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer srv-key"},
        json={"model": "qwen-turbo", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "mock 回复"


def _make_qwen_web_gateway(mock_url: str) -> TestClient:
    cfg = Config(
        host="127.0.0.1", port=5005, authorization=["srv-key"],
        doubao_cookies=[], doubao_session_ids=[],
        ark_api_key="", compat_base_url="", compat_api_key="", compat_model="",
        qwen_cookies=["tongyi_sso_ticket=tk123; aliyun_choice=intl"],
        qwen_web_base=mock_url,
    )
    return TestClient(create_app(cfg))


def test_qwen_web_non_stream(mock_server_url):
    client = _make_qwen_web_gateway(mock_server_url)
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer srv-key"},
        json={"model": "qwen-turbo", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "千问 回复"


def test_qwen_web_stream(mock_server_url):
    client = _make_qwen_web_gateway(mock_server_url)
    with client.stream(
        "POST", "/v1/chat/completions",
        headers={"Authorization": "Bearer srv-key"},
        json={"model": "qwen-turbo", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "[DONE]" in body
    contents = []
    for line in body.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            ev = json.loads(line[6:])
            for choice in ev.get("choices", []):
                d = choice.get("delta", {})
                if d.get("content"):
                    contents.append(d["content"])
    assert "".join(contents) == "千问 回复"


def test_status_lists_new_channels(mock_server_url):
    client = _make_deepseek_gateway(mock_server_url)
    resp = client.get("/api/status")
    keys = [c["key"] for c in resp.json()["channels"]]
    assert "deepseek_web" in keys
    assert "qwen_api" in keys


def test_reload_endpoint(mock_server_url):
    client = _make_deepseek_gateway(mock_server_url)
    resp = client.post("/api/reload")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------- 控制台 ----------
def _make_gateway_with_console(mock_url: str) -> TestClient:
    cfg = Config(
        host="127.0.0.1", port=5005, authorization=["srv-key"], console_key="sec-123",
        doubao_cookies=[], doubao_session_ids=[],
        ark_api_key="",
        compat_base_url=f"{mock_url}/v1", compat_api_key="k", compat_model="mock",
    )
    return TestClient(create_app(cfg))


def test_console_page_served(mock_server_url):
    client = _make_gateway_with_console(mock_server_url)
    resp = client.get("/console")
    assert resp.status_code == 200
    assert "IRmAPI" in resp.text


def test_console_api_requires_key(mock_server_url):
    client = _make_gateway_with_console(mock_server_url)
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"X-Console-Key": "sec-123"}).status_code == 200


def test_playground_non_stream(mock_server_url):
    client = _make_gateway_with_console(mock_server_url)
    resp = client.post(
        "/api/playground",
        headers={"Content-Type": "application/json", "X-Console-Key": "sec-123"},
        json={"model": "compat-mock", "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "mock 回复"


def test_playground_stream(mock_server_url):
    client = _make_gateway_with_console(mock_server_url)
    with client.stream(
        "POST", "/api/playground",
        headers={"Content-Type": "application/json", "X-Console-Key": "sec-123"},
        json={"model": "compat-mock", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "[DONE]" in body
    contents = []
    for line in body.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            ev = json.loads(line[6:])
            for choice in ev.get("choices", []):
                d = choice.get("delta", {})
                if d.get("content"):
                    contents.append(d["content"])
    assert "".join(contents) == "mock 回复"
