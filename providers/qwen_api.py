"""通义千问（阿里云百炼 DashScope）Provider —— 官方 OpenAI 兼容 API。

base_url = https://dashscope.aliyuncs.com/compatible-mode/v1
开通：https://bailian.console.aliyun.com 创建 API-KEY 并开通 qwen 模型即可。
百炼平台对新用户赠送免费 token 额度（qwen-turbo / qwen-plus 等），适合低成本跑量。
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

QWEN_DEFAULT_MODEL = "qwen-turbo"


class QwenApiProvider(BaseProvider):
    key = "qwen_api"
    label = "通义千问（阿里云百炼，官方免费额度）"

    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0))

    def _real_model(self, model: str) -> str:
        m = model.lower()
        # qwen 前缀（含 qwen- 与纯别名）都映射到百炼模型；未指定具体型号时用默认
        for name in ("qwen-turbo", "qwen-plus", "qwen-max", "qwen-long", "qwen-flash"):
            if m.startswith(name) or m == name:
                return name
        if m.startswith("qwen-"):
            return m  # 其它 qwen-xxx 视为真实模型 ID 透传
        return QWEN_DEFAULT_MODEL

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = False,
        **kwargs: Any,
    ) -> Iterator[str] | dict[str, Any]:
        real_model = self._real_model(model)
        payload: dict[str, Any] = {"model": real_model, "messages": messages, "stream": stream}
        for k in ("temperature", "top_p", "max_tokens", "max_completion_tokens", "user"):
            if kwargs.get(k) is not None:
                payload[k] = kwargs[k]

        base = self.config.qwen_base_url.rstrip("/")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.qwen_api_key}",
        }
        try:
            resp = self.client.post(f"{base}/chat/completions", headers=headers, json=payload)
        except httpx.HTTPError as e:
            raise ProviderError(f"连接通义千问失败: {e}", 502)
        if resp.status_code != 200:
            raise ProviderError(
                f"通义千问返回 HTTP {resp.status_code}: {resp.text[:300]}"
                "（Key 无效 / 额度不足 / 模型未开通）",
                502,
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
            raise ProviderError(f"解析通义千问响应流失败: {e}", 502)
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
