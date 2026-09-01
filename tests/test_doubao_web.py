"""豆包网页版 Provider 单元测试（mock 掉网络请求）。"""
from __future__ import annotations

import json

import httpx
import pytest

from gateway.config import Config
from gateway.sse import iter_sse_events
from providers.base import ProviderError
from providers.doubao_web import DoubaoWebProvider


def make_provider(cookies=("cookie-1", "cookie-2"), sids=(), ms_token="", a_bogus=""):
    cfg = Config(
        host="127.0.0.1",
        port=5005,
        authorization=[],
        doubao_cookies=list(cookies),
        doubao_session_ids=list(sids),
        doubao_ms_token=ms_token,
        doubao_a_bogus=a_bogus,
        doubao_retry=2,
        doubao_clean_conversation=False,
    )
    return DoubaoWebProvider(cfg)


# ---------- 消息合并 ----------
def test_single_message_plain():
    p = make_provider()
    text = p._prepare_text([{"role": "user", "content": "你好"}])
    assert text == "你好"


def test_multi_turn_merge_with_markers():
    p = make_provider()
    text = p._prepare_text(
        [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "1+1?"},
            {"role": "assistant", "content": "2"},
            {"role": "user", "content": "再问"},
        ]
    )
    assert "<|im_start|>system\n你是助手<|im_end|>" in text
    assert "<|im_start|>user\n1+1?<|im_end|>" in text


def test_content_parts_text_extraction():
    p = make_provider()
    text = p._content_to_text(
        [{"type": "text", "text": "A"}, {"type": "image_url", "image_url": {"url": "x"}}]
    )
    assert text == "A"


# ---------- 凭据与签名 ----------
def test_credentials_prefer_full_cookie():
    p = make_provider(cookies=("full-cookie",), sids=("sid-only",))
    assert p._credentials() == ["full-cookie"]


def test_credentials_fallback_to_sessionid_synth():
    p = make_provider(cookies=(), sids=("sid-1",))
    creds = p._credentials()
    assert "sessionid=sid-1" in creds[0]


def test_credentials_raise_when_none():
    p = make_provider(cookies=(), sids=())
    with pytest.raises(ProviderError):
        p._credentials()


def test_client_credential_mode_uses_passed_cookie_or_sessionid(monkeypatch):
    """客户端直传凭据：完整 Cookie 原样使用，sessionid 自动合成。"""
    p = make_provider(cookies=("server-cookie",), sids=())

    # 用 monkeypatch 把 _chat_request 拦截，检查传入的 cookie
    captured = {}

    def fake_request(cookie, text, conversation_id, query, timeout=300):
        captured["cookie"] = cookie
        return httpx.Response(400, text="")  # 只验证 cookie 使用即可

    monkeypatch.setattr(p, "_chat_request", fake_request)
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "hi"}], "doubao-web", credential_mode="client", credential="sessionid=abc; ttwid=xyz")
    assert "sessionid=abc" in captured["cookie"]

    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "hi"}], "doubao-web", credential_mode="client", credential="raw-sid")
    assert "sessionid=raw-sid" in captured["cookie"]


def test_signatures_are_configurable():
    p = make_provider(ms_token="fixed-ms", a_bogus="fixed-ab")
    assert p._ms_token() == "fixed-ms"
    assert p._a_bogus() == "fixed-ab"
    assert p._build_query()["msToken"] == "fixed-ms"
    assert p._build_query()["a_bogus"] == "fixed-ab"


# ---------- 请求体 ----------
def test_payload_has_real_fields():
    p = make_provider()
    payload = p._build_payload("你好", "0")
    assert payload["messages"][0]["content_type"] == 2001
    assert json.loads(payload["messages"][0]["content"]) == {"text": "你好"}
    assert payload["completion_option"]["need_create_conversation"] is True
    assert "local_message_id" in payload


# ---------- SSE 提取 ----------
def test_extract_delta_from_real_format():
    p = make_provider()
    # 真实格式：event_data 是 JSON 字符串，内含 message.content(JSON字符串)->text
    event = {
        "event_type": 2001,
        "event_data": json.dumps(
            {"message": {"content": json.dumps({"text": "你好"})}}, ensure_ascii=False
        ),
    }
    assert p._extract_delta(event) == "你好"


def test_extract_conversation_id_from_2002():
    p = make_provider()
    event = {
        "event_type": 2002,
        "event_data": json.dumps({"conversation_id": "12345"}),
    }
    assert p._extract_conversation_id(event) == "12345"


# ---------- 流转换（mock 响应） ----------
def _fake_response(lines: list[str]) -> httpx.Response:
    return httpx.Response(200, text="".join(lines))


def _doubao_event(event_type, event_data: dict | None = None):
    ev = {"event_type": event_type}
    if event_data is not None:
        ev["event_data"] = json.dumps(event_data, ensure_ascii=False)
    return "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"


def test_non_stream_assembles_full_text():
    p = make_provider()
    lines = [
        _doubao_event(2002, {"conversation_id": "conv-9"}),
        _doubao_event(2001, {"message": {"content": json.dumps({"text": "你"})}}),
        _doubao_event(2001, {"message": {"content": json.dumps({"text": "好"})}}),
        _doubao_event(2003, {}),
    ]
    resp = _fake_response(lines)
    result = p._non_stream(resp, "cookie-1")
    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["content"] == "你好"


def test_stream_yields_openai_chunks():
    p = make_provider()
    lines = [
        _doubao_event(2001, {"message": {"content": json.dumps({"text": "哈"})}}),
        _doubao_event(2001, {"message": {"content": json.dumps({"text": "喽"})}}),
        _doubao_event(2003, {}),
    ]
    resp = _fake_response(lines)
    chunks = list(p._stream(resp, "cookie-1"))
    sse_text = "".join(chunks)
    assert "chat.completion.chunk" in sse_text
    assert "[DONE]" in sse_text
    contents = []
    for ev in iter_sse_events(sse_text):
        for choice in ev.get("choices", []):
            d = choice.get("delta", {})
            if d.get("content"):
                contents.append(d["content"])
    assert "".join(contents) == "哈喽"


def test_error_event_raises():
    p = make_provider()
    err_line = "data: " + json.dumps({"code": 4001, "message": "风控"}) + "\n\n"
    resp = _fake_response([err_line])
    with pytest.raises(ProviderError):
        p._non_stream(resp, "cookie-1")
