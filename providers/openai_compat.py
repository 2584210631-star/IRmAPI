"""通用 OpenAI 兼容上游 Provider。

可接任意 OpenAI 兼容服务（DeepSeek / Kimi / 硅基流动 / 本地 Ollama 等），
通过 COMPAT_BASE_URL / COMPAT_API_KEY / COMPAT_MODEL 配置。
"""
from __future__ import annotations

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


class OpenAICompatProvider(BaseProvider):
    key = "openai_compat"
    label = "通用 OpenAI 兼容上游"

    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0))

    def _real_model(self, model: str) -> str:
        m = model.lower()
        if m.startswith("compat-"):
            return self.config.compat_model or model[len("compat-"):]
        if m.startswith(("deepseek-", "kimi-", "qwen-", "glm-", "moonshot-")):
            # 若配置了默认模型则回落，否则透传原始模型名
            return model
        return self.config.compat_model or model

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
        for k in ("temperature", "top_p", "max_tokens", "max_completion_tokens", "user"):
            if kwargs.get(k) is not None:
                payload[k] = kwargs[k]

        base = self.config.compat_base_url.rstrip("/")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.compat_api_key}",
        }
        try:
            resp = self.client.post(f"{base}/chat/completions", headers=headers, json=payload)
        except httpx.HTTPError as e:
            raise ProviderError(f"连接上游失败: {e}", 502)

        if resp.status_code != 200:
            raise ProviderError(
                f"上游返回 HTTP {resp.status_code}: {resp.text[:300]}", 502
            )

        if stream:
            return self._forward_stream(resp, real_model)
        return self._forward_non_stream(resp, real_model)

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
            raise ProviderError(f"解析上游响应流失败: {e}", 502)
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
