"""OpenAI 兼容请求/响应模型。"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessageContent(BaseModel):
    type: str = "text"
    text: Optional[str] = None
    image_url: Optional[dict[str, Any]] = None


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str | list[ChatMessageContent | dict[str, Any]] | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "doubao-web"
    messages: list[ChatMessage] = Field(default_factory=list)
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    user: Optional[str] = None
    # 透传给上游的其它参数
    extra: dict[str, Any] = Field(default_factory=dict, exclude=True)
