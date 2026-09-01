"""Provider 抽象基类。

所有上游通道都实现同一个接口：
  - chat(messages, model, stream, ...) -> 迭代器（产出 str SSE 文本）或完整响应 dict
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any


class ProviderError(Exception):
    """上游返回业务错误。"""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class BaseProvider(ABC):
    """上游通道基类。"""

    key: str = "base"
    label: str = "Base"

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = False,
        **kwargs: Any,
    ) -> Iterator[str] | dict[str, Any]:
        """发起对话。

        - stream=True  返回一个 str 迭代器，逐条产出 OpenAI SSE chunk 文本；
        - stream=False 返回完整的 chat.completion 字典。
        失败时抛 ProviderError。
        """
        raise NotImplementedError

    @property
    def enabled(self) -> bool:
        return True
