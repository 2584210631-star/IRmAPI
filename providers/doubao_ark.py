"""豆包官方火山方舟（Volcengine Ark）Provider。

豆包官方开放 API，完全兼容 OpenAI 协议：
  base_url = https://ark.cn-beijing.volces.com/api/v3
需要你在火山方舟控制台开通模型并创建 API Key（lite 模型有每日免费额度）。
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import httpx

from gateway.config import Config
from gateway.response import (
    build_final,
    build_start_chunk,
    build_stop_chunk,
    build_content_chunk,
    finish_stream_sse,
)
from gateway.sse import iter_sse_events
from providers.base import BaseProvider, ProviderError


class DoubaoArkProvider(BaseProvider):
    key = "doubao_ark"
    label = "豆包官方火山方舟（需 API Key）"

    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0))

    def _real_model(self, model: str) -> str:
        """客户端传入的模型名优先；纯别名则回落到配置的默认模型。"""
        m = model.lower()
        if m.startswith("ark-") or m.startswith("doubao-ark"):
            # ark- 前缀是路由标识，不代表真实模型名
            return self.config.ark_model
        if m.startswith("doubao-"):
            # doubao-xxx 视为真实模型 ID 直接透传
            return model
        return self.config.ark_model

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = False,
        **kwargs: Any,
    ) -> Iterator[str] | dict[str, Any]:
        real_model = self._real_model(model)
        payload: dict[str, Any] = {
            "model": real_model,
            "messages": messages,
            "stream": stream,
        }
        # 透传常用采样参数
        for k in ("temperature", "top_p", "max_tokens", "max_completion_tokens", "user"):
            if kwargs.get(k) is not None:
                payload[k] = kwargs[k]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.ark_api_key}",
        }

        try:
            resp = self.client.post(
                f"{self.config.ark_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"连接火山方舟失败: {e}", 502)

        if resp.status_code != 200:
            detail = resp.text[:300]
            raise ProviderError(f"火山方舟返回 HTTP {resp.status_code}: {detail}", 502)

        if stream:
            return self._forward_stream(resp, real_model)
        return self._forward_non_stream(resp, real_model)

    def _forward_stream(self, resp: httpx.Response, model: str) -> Iterator[str]:
        """方舟已是 OpenAI 格式，直接转发其 SSE。"""
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
            raise ProviderError(f"解析方舟响应流失败: {e}", 502)
        yield build_stop_chunk(chunk_id)
        yield finish_stream_sse()

    def _forward_non_stream(self, resp: httpx.Response, model: str) -> dict[str, Any]:
        data = resp.json()
        choices = data.get("choices") or []
        content = ""
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content") or ""
        usage = data.get("usage") or {}
        return build_final(
            f"chatcmpl-{uuid.uuid4().hex}",
            model,
            content,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
