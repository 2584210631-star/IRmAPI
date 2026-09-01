"""模型名 -> Provider 的路由规则。"""
from __future__ import annotations

from gateway.config import Config


class RoutingError(Exception):
    pass


def resolve_provider_key(model: str, config: Config) -> str:
    """根据模型名解析出应使用的 provider key。

    规则（按优先级）：
      1. ark-* / doubao-ark-*           -> doubao_ark（豆包官方方舟）
      2. doubao-web* / doubao-free* / web-* -> doubao_web（豆包网页版免 Key）
      3. doubao*                        -> doubao_ark（配了官方 key 优先）否则 doubao_web
      4. deepseek-*                     -> deepseek_web（网页版免 Key / 官方 Key 兜底）
      5. qwen-*                         -> qwen_web（网页版免 Key）否则 qwen_api（百炼官方）
      6. kimi-* / glm-* / moonshot-* / compat-* -> openai_compat（通用兼容上游）
      7. 其它未知模型                   -> 默认豆包网页版
    """
    m = model.lower()

    # 方舟官方通道
    if m.startswith("ark-") or m.startswith("doubao-ark"):
        if not config.ark_enabled:
            raise RoutingError("模型路由到 doubao_ark，但未配置 ARK_API_KEY")
        return "doubao_ark"

    # 豆包网页版（免 Key）通道
    if m.startswith("doubao-web") or m.startswith("doubao-free") or m.startswith("web-"):
        if not config.doubao_web_enabled:
            raise RoutingError(
                "模型路由到 doubao_web，但未配置凭据：请设置 DOUBAO_COOKIE_1（完整 Cookie）"
                "或 DOUBAO_SESSIONIDS"
            )
        return "doubao_web"

    # 官方 key 可用时，普通 doubao 模型走官方（稳定、免费额度）
    if "doubao" in m:
        if config.ark_enabled:
            return "doubao_ark"
        if config.doubao_web_enabled:
            return "doubao_web"
        raise RoutingError("未配置任何豆包凭据（ARK_API_KEY 或 DOUBAO_SESSIONIDS）")

    # DeepSeek（网页版免 Key 优先；官方 Key 兜底）
    if m.startswith("deepseek-"):
        if not config.deepseek_enabled:
            raise RoutingError(
                "模型路由到 deepseek_web，但未配置凭据：DEEPSEEK_COOKIE_1 / DEEPSEEK_TOKEN"
                "（网页版免 Key）或 DEEPSEEK_API_KEY（官方）"
            )
        return "deepseek_web"

    # 通义千问（网页版 Cookie 免 Key 优先；百炼官方 Key 兜底）
    if m.startswith("qwen-"):
        if not config.qwen_enabled:
            raise RoutingError(
                "模型路由到 qwen 通道，但未配置凭据：QWEN_COOKIE_1（通义千问网页版，免 Key）"
                "或 QWEN_API_KEY（阿里云百炼，官方免费额度）"
            )
        return "qwen_web" if config.qwen_cookies else "qwen_api"

    # 通用 OpenAI 兼容上游（Kimi / GLM / Moonshot / compat-* 等）
    if (
        m.startswith("compat-")
        or m.startswith("kimi-")
        or m.startswith("glm-")
        or m.startswith("moonshot-")
    ):
        if not config.compat_enabled:
            raise RoutingError(
                "模型路由到 openai_compat，但未配置 COMPAT_BASE_URL / COMPAT_API_KEY"
            )
        return "openai_compat"

    # 未知模型名兜底：豆包网页版
    if config.doubao_web_enabled:
        return "doubao_web"
    if config.ark_enabled:
        return "doubao_ark"
    raise RoutingError("没有可用的模型通道，请先在 .env 配置豆包凭据")
