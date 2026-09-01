"""核心组件单元测试（不依赖网络）。"""
from __future__ import annotations

import json

import pytest

from gateway.config import Config
from gateway.response import build_error, build_final, build_stop_chunk
from gateway.routing import RoutingError, resolve_provider_key
from gateway.sse import iter_sse_events
from gateway.tokens import TokenPool, _AuthError


# ---------- Config 工厂 ----------
def make_config(**overrides) -> Config:
    base = dict(
        authorization=["srv-key"],
        doubao_session_ids=["sid-a", "sid-b"],
        ark_api_key="",
        ark_model="doubao-seed-1-6-lite-251015",
        compat_base_url="",
        compat_api_key="",
        deepseek_token="",
        deepseek_api_key="",
        deepseek_web_base="https://chat.deepseek.com",
        qwen_api_key="",
        qwen_cookies=[],
        qwen_web_base="https://qianwen.biz.aliyun.com",
    )
    base.update(overrides)
    return Config(
        host="127.0.0.1",
        port=5005,
        authorization=base["authorization"],
        doubao_session_ids=base["doubao_session_ids"],
        ark_api_key=base["ark_api_key"],
        ark_model=base["ark_model"],
        compat_base_url=base["compat_base_url"],
        compat_api_key=base["compat_api_key"],
        deepseek_token=base["deepseek_token"],
        deepseek_api_key=base["deepseek_api_key"],
        deepseek_web_base=base["deepseek_web_base"],
        qwen_api_key=base["qwen_api_key"],
        qwen_cookies=base["qwen_cookies"],
        qwen_web_base=base["qwen_web_base"],
    )


# ---------- TokenPool ----------
def test_token_pool_uses_server_credentials_when_matching_auth_key():
    cfg = make_config()
    pool = TokenPool(cfg)
    info = pool.resolve("Bearer srv-key")
    assert info.mode == "server"
    assert info.credential == "srv-key"


def test_token_pool_uses_client_token_directly():
    cfg = make_config()
    pool = TokenPool(cfg)
    info = pool.resolve("Bearer my-sessionid")
    assert info.mode == "client"
    assert info.credential == "my-sessionid"


def test_token_pool_picks_random_from_comma_list():
    cfg = make_config()
    pool = TokenPool(cfg)
    info = pool.resolve("Bearer a,b,c")
    assert info.mode == "client"
    assert info.credential in ("a", "b", "c")


def test_token_pool_raises_without_auth():
    cfg = make_config()
    pool = TokenPool(cfg)
    with pytest.raises(_AuthError):
        pool.resolve(None)


# ---------- Routing ----------
def test_route_ark_when_model_has_doubao_and_key_set():
    cfg = make_config(ark_api_key="k")
    assert resolve_provider_key("doubao-seed-1-6-lite-251015", cfg) == "doubao_ark"


def test_route_doubao_web_explicit():
    cfg = make_config()
    assert resolve_provider_key("doubao-web", cfg) == "doubao_web"
    assert resolve_provider_key("doubao-free", cfg) == "doubao_web"


def test_route_doubao_web_default_when_no_ark_key():
    cfg = make_config()
    assert resolve_provider_key("doubao", cfg) == "doubao_web"
    assert resolve_provider_key("随便的模型名", cfg) == "doubao_web"


def test_route_ark_raises_if_no_key():
    cfg = make_config()
    with pytest.raises(RoutingError):
        resolve_provider_key("ark-something", cfg)


def test_route_compat():
    cfg = make_config(compat_base_url="https://x", compat_api_key="k")
    assert resolve_provider_key("compat-anything", cfg) == "openai_compat"
    assert resolve_provider_key("kimi-anything", cfg) == "openai_compat"


def test_route_deepseek_web():
    cfg = make_config(deepseek_token="t")
    assert resolve_provider_key("deepseek-chat", cfg) == "deepseek_web"
    assert resolve_provider_key("deepseek-reasoner", cfg) == "deepseek_web"


def test_route_deepseek_raises_without_cred():
    cfg = make_config()
    with pytest.raises(RoutingError):
        resolve_provider_key("deepseek-chat", cfg)


def test_route_qwen_api():
    cfg = make_config(qwen_api_key="k")
    assert resolve_provider_key("qwen-turbo", cfg) == "qwen_api"


def test_route_qwen_web_prefers_cookie():
    cfg = make_config(qwen_api_key="k", qwen_cookies=["tongyi_sso_ticket=abc"])
    assert resolve_provider_key("qwen-turbo", cfg) == "qwen_web"


def test_route_qwen_raises_without_cred():
    cfg = make_config()
    with pytest.raises(RoutingError):
        resolve_provider_key("qwen-turbo", cfg)


# ---------- SSE ----------
def test_sse_parser_basic():
    events = list(iter_sse_events('data: {"a":1}\n\ndata: {"b":2}\n\n'))
    assert events == [{"a": 1}, {"b": 2}]


def test_sse_parser_with_event_field_and_done():
    events = list(iter_sse_events('event: x\ndata: {"a":1}\n\ndata: [DONE]\n\n'))
    assert events == [{"a": 1}, {"_done": True}]


# ---------- Response builders ----------
def test_build_final_shape():
    r = build_final("id-1", "doubao-web", "你好", completion_tokens=10)
    assert r["object"] == "chat.completion"
    assert r["choices"][0]["message"]["content"] == "你好"
    assert r["usage"]["total_tokens"] == 10


def test_build_error_shape():
    r = build_error(401, "没有凭据", "invalid_request_error")
    assert r["error"]["code"] == 401


def test_build_stop_chunk():
    s = build_stop_chunk("c", "m")
    assert "chat.completion.chunk" in s
    assert "finish_reason" in s
