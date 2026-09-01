"""OpenAI chat.completion / chat.completion.chunk 响应构建。"""
from __future__ import annotations

import time
from typing import Any

from gateway.sse import encode_sse, encode_sse_done


def _now() -> int:
    return int(time.time())


def _usage(completion_tokens: int = 0, prompt_tokens: int = 0) -> dict[str, Any]:
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def build_chunk(
    chunk_id: str,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
    usage: dict[str, Any] | None = None,
) -> str:
    """构造一条流式 chunk 的 SSE 文本。"""
    data = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": _now(),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage:
        data["usage"] = usage
    return encode_sse(data)


def build_start_chunk(chunk_id: str, model: str) -> str:
    """流式开始时先发一条 role 占位 chunk。"""
    return build_chunk(chunk_id, model, {"role": "assistant", "content": ""})


def build_content_chunk(chunk_id: str, model: str, content: str) -> str:
    return build_chunk(chunk_id, model, {"content": content})


def build_reasoning_chunk(chunk_id: str, model: str, reasoning: str) -> str:
    return build_chunk(chunk_id, model, {"reasoning_content": reasoning})


def build_stop_chunk(chunk_id: str, model: str, finish_reason: str = "stop") -> str:
    return build_chunk(chunk_id, model, {}, finish_reason=finish_reason)


def build_final(
    completion_id: str,
    model: str,
    content: str,
    reasoning: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> dict[str, Any]:
    """构造非流式完整响应对象。"""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": _now(),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": _usage(completion_tokens=completion_tokens, prompt_tokens=prompt_tokens),
    }


def build_error(
    status_code: int,
    message: str,
    err_type: str = "api_error",
    param: str | None = None,
) -> dict[str, Any]:
    """构造 OpenAI 风格错误响应。"""
    err: dict[str, Any] = {
        "message": message,
        "type": err_type,
        "param": param,
        "code": status_code,
    }
    return {"error": err}


def sse_stream(iterable) -> Any:
    """把一个 str 迭代器包装成 FastAPI 的 StreamingResponse。"""
    from fastapi.responses import StreamingResponse

    return StreamingResponse(iterable, media_type="text/event-stream")


def finish_stream_sse() -> str:
    return encode_sse_done()
