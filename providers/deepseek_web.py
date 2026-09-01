"""DeepSeek 网页版（chat.deepseek.com）逆向 Provider —— 免 Key，用浏览器 Cookie / Token。

原理（与豆包网页版同理）：
  1) 登录 chat.deepseek.com，从浏览器抓【完整 Cookie】（或直接复制网页版 token）。
  2) 用 Cookie / Bearer Token 调 DeepSeek 网页版后端 /api/v0/chat/completions。
  3) DeepSeek 网页版返回的就是标准 OpenAI 格式，直接转发。

凭据（任选其一）：
  - DEEPSEEK_COOKIE_1=...（完整 Cookie，推荐；会自动从中提取 token= 字段）
  - DEEPSEEK_TOKEN=...（登录后浏览器里 Authorization: Bearer 后面那串）
  - DEEPSEEK_API_KEY=...（官方 api.deepseek.com，按量计费；上面两种都没有时的稳定兜底）

注意：网页版逆向依赖 DeepSeek 前端接口，改版可能失效；请遵守服务条款，仅供个人学习自用。
"""
from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from typing import Any

import httpx

from gateway.config import Config
from gateway.response import (
    build_content_chunk,
    build_final,
    build_start_chunk,
    build_stop_chunk,
    finish_stream_sse,
)
from gateway.sse import iter_sse_events
from providers.base import BaseProvider, ProviderError

DEEPSEEK_WEB_BASE = "https://chat.deepseek.com"
DEEPSEEK_WEB_ENDPOINT = "/api/v0/chat/completions"
DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


class DeepSeekWebProvider(BaseProvider):
    key = "deepseek_web"
    label = "DeepSeek 网页版（免 Key / 浏览器 Cookie）"

    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0))

    # ---------- 凭据 ----------
    @staticmethod
    def _extract_token(cookie: str) -> str:
        for part in cookie.split(";"):
            part = part.strip()
            if part.lower().startswith("token="):
                return part.split("=", 1)[1].strip()
        return ""

    def _credentials(self) -> list[dict[str, str]]:
        """返回凭据列表，每项 {cookie, token} 或 {api_key}。"""
        creds: list[dict[str, str]] = []
        for c in self.config.deepseek_cookies:
            creds.append({"cookie": c, "token": self._extract_token(c)})
        if self.config.deepseek_token and not creds:
            creds.append({"cookie": "", "token": self.config.deepseek_token})
        if self.config.deepseek_api_key and not creds:
            creds.append({"api_key": self.config.deepseek_api_key})
        if not creds:
            raise ProviderError(
                "DeepSeek 网页版通道未配置凭据：请填 DEEPSEEK_COOKIE_1（完整 Cookie）"
                "或 DEEPSEEK_TOKEN，或 DEEPSEEK_API_KEY（官方，按量计费）",
                401,
            )
        return creds

    # ---------- 请求 ----------
    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = False,
        **kwargs: Any,
    ) -> Iterator[str] | dict[str, Any]:
        cred = random.choice(self._credentials())

        # 官方 Key 兜底通道（api.deepseek.com）
        if "api_key" in cred:
            return self._chat_official_api(messages, stream, cred["api_key"], kwargs)

        # 网页版逆向通道
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "Origin": DEEPSEEK_WEB_BASE,
            "Referer": f"{DEEPSEEK_WEB_BASE}/",
            "User-Agent": _UA,
            "X-App-Version": "1.4.33",
        }
        if cred.get("token"):
            headers["Authorization"] = f"Bearer {cred['token']}"
        if cred.get("cookie"):
            headers["Cookie"] = cred["cookie"]

        payload: dict[str, Any] = {
            "model": "deepseek_chat",
            "messages": messages,
            "stream": stream,
            "presence_penalty": 0,
            "frequency_penalty": 0,
        }
        for k in ("temperature", "top_p", "max_tokens", "max_completion_tokens", "user"):
            if kwargs.get(k) is not None:
                payload[k] = kwargs[k]

        try:
            resp = self.client.post(
                f"{self.config.deepseek_web_base}{DEEPSEEK_WEB_ENDPOINT}",
                headers=headers,
                json=payload,
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"连接 DeepSeek 网页版失败: {e}", 502)

        if resp.status_code != 200:
            raise ProviderError(
                f"DeepSeek 网页版返回 HTTP {resp.status_code}: {resp.text[:300]}"
                "（Cookie/token 可能已过期，或网页版接口已改版）",
                502,
            )

        if stream:
            return self._forward_stream(resp, model)
        return self._forward_non_stream(resp, model)

    def _chat_official_api(
        self,
        messages: list[dict[str, Any]],
        stream: bool,
        api_key: str,
        kwargs: dict[str, Any],
    ) -> Iterator[str] | dict[str, Any]:
        """官方 api.deepseek.com（OpenAI 兼容），用作网页版不可用时的稳定兜底。"""
        payload: dict[str, Any] = {"model": "deepseek-chat", "messages": messages, "stream": stream}
        for k in ("temperature", "top_p", "max_tokens", "max_completion_tokens", "user"):
            if kwargs.get(k) is not None:
                payload[k] = kwargs[k]
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        try:
            resp = self.client.post(
                f"{DEEPSEEK_API_BASE}/chat/completions", headers=headers, json=payload
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"连接 DeepSeek 官方 API 失败: {e}", 502)
        if resp.status_code != 200:
            raise ProviderError(f"DeepSeek 官方 API 返回 HTTP {resp.status_code}: {resp.text[:300]}", 502)
        if stream:
            return self._forward_stream(resp, model)
        return self._forward_non_stream(resp, model)

    # ---------- 转发 ----------
    def _forward_stream(self, resp: httpx.Response, model: str) -> Iterator[str]:
        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
        yield build_start_chunk(chunk_id, model)
        buffer = ""
        try:
            for raw in resp.iter_text():
                buffer += raw
                for event in iter_sse_events(buffer):
                    if event.get("_done"):
                        yield finish_stream_sse()
                        return
                    for choice in event.get("choices", []):
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            yield build_content_chunk(chunk_id, model, delta["content"])
                        if choice.get("finish_reason"):
                            yield build_stop_chunk(chunk_id, choice["finish_reason"])
                buffer = ""
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"解析 DeepSeek 响应流失败: {e}", 502)
        yield build_stop_chunk(chunk_id)
        yield finish_stream_sse()

    def _forward_non_stream(self, resp: httpx.Response, model: str) -> dict[str, Any]:
        data = resp.json()
        choices = data.get("choices") or []
        content = ""
        if choices:
            content = (choices[0].get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        return build_final(
            f"chatcmpl-{uuid.uuid4().hex}",
            model,
            content,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
