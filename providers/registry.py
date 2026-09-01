"""Provider 注册表：按 key 创建/获取 Provider 实例。"""
from __future__ import annotations

from gateway.config import Config
from providers.base import BaseProvider
from providers.deepseek_web import DeepSeekWebProvider
from providers.doubao_ark import DoubaoArkProvider
from providers.doubao_web import DoubaoWebProvider
from providers.openai_compat import OpenAICompatProvider
from providers.qwen_api import QwenApiProvider
from providers.qwen_web import QwenWebProvider


class ProviderRegistry:
    def __init__(self, config: Config):
        self.config = config
        self._providers: dict[str, BaseProvider] = {}

    def get(self, key: str) -> BaseProvider:
        if key not in self._providers:
            self._providers[key] = self._build(key)
        return self._providers[key]

    def _build(self, key: str) -> BaseProvider:
        if key == "doubao_web":
            return DoubaoWebProvider(self.config)
        if key == "doubao_ark":
            return DoubaoArkProvider(self.config)
        if key == "openai_compat":
            return OpenAICompatProvider(self.config)
        if key == "deepseek_web":
            return DeepSeekWebProvider(self.config)
        if key == "qwen_api":
            return QwenApiProvider(self.config)
        if key == "qwen_web":
            return QwenWebProvider(self.config)
        raise ValueError(f"未知 provider: {key}")

    def list_models(self) -> list[str]:
        """返回对外可用的模型列表。"""
        models: list[str] = []
        if self.config.ark_enabled:
            models += ["doubao-ark", self.config.ark_model]
        if self.config.doubao_web_enabled:
            models += ["doubao-web", "doubao", "doubao-free", "doubao-web-2026"]
        if self.config.compat_enabled:
            models += ["compat-" + (self.config.compat_model or "default")]
        if self.config.deepseek_enabled:
            models += ["deepseek-web", "deepseek-chat", "deepseek-reasoner"]
        if self.config.qwen_enabled:
            models += ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-long"]
        if not models:
            models = ["doubao-web"]
        return models
