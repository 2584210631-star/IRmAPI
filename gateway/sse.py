"""SSE（Server-Sent Events）编解码工具。"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any


def encode_sse(data: dict[str, Any]) -> str:
    """把字典编码为一条 OpenAI 风格的 SSE 消息（data: json\n\n）。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def encode_sse_done() -> str:
    return "data: [DONE]\n\n"


def iter_sse_events(buffer: str) -> Iterator[dict[str, Any]]:
    """把一段 SSE 文本按空行切分为事件，解析其中的 JSON 数据。

    兼容两种常见格式：
      data: {...}\n\n
      event: xxx\ndata: {...}\n\n
    """
    # 按空行切分，丢弃纯空白块
    for block in re.split(r"\r?\n\r?\n", buffer):
        if not block.strip():
            continue
        data_lines: list[str] = []
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        if not data_lines:
            continue
        payload = "\n".join(data_lines)
        if payload == "[DONE]":
            yield {"_done": True}
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            # 非 JSON 的数据行，原样包一层透传
            yield {"_raw": payload}
