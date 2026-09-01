"""配置加载：从 .env / 环境变量读取，所有项带默认值。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 优先加载项目根目录下的 .env；Android 上通过 IRMAPI_ENV_FILE 指向可写目录
_ROOT = Path(__file__).resolve().parent.parent
_env_file = os.environ.get("IRMAPI_ENV_FILE")
if _env_file:
    load_dotenv(_env_file)
else:
    load_dotenv(_ROOT / ".env")


def _split_csv(value: str | None) -> list[str]:
    """把逗号分隔的字符串拆成去空格、去空项的列表。"""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


@dataclass
class Config:
    # 服务
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("PORT", "5005")))
    authorization: list[str] = field(default_factory=lambda: _split_csv(_env("AUTHORIZATION")))
    # 控制台访问口令（可选；设置了则打开 /console 需要输入）
    console_key: str = field(default_factory=lambda: _env("CONSOLE_KEY"))

    # 豆包网页版
    # 完整 Cookie（推荐）：DOUBAO_COOKIE_1、DOUBAO_COOKIE_2 ... 支持多账号轮询
    doubao_cookies: list[str] = field(default_factory=list)
    # 仅 sessionid（兜底，可能需要配合完整 Cookie 才稳定）
    doubao_session_ids: list[str] = field(default_factory=lambda: _split_csv(_env("DOUBAO_SESSIONIDS")))
    doubao_ms_token: str = field(default_factory=lambda: _env("DOUBAO_MS_TOKEN"))
    doubao_a_bogus: str = field(default_factory=lambda: _env("DOUBAO_A_BOGUS"))
    doubao_device_id: str = field(default_factory=lambda: _env("DOUBAO_DEVICE_ID"))
    doubao_web_id: str = field(default_factory=lambda: _env("DOUBAO_WEB_ID"))
    doubao_retry: int = field(default_factory=lambda: int(_env("DOUBAO_RETRY", "3")))
    doubao_clean_conversation: bool = field(
        default_factory=lambda: _env("DOUBAO_CLEAN_CONVERSATION", "true").lower() == "true"
    )

    # 豆包官方方舟
    ark_api_key: str = field(default_factory=lambda: _env("ARK_API_KEY"))
    ark_model: str = field(default_factory=lambda: _env("ARK_MODEL", "doubao-seed-1-6-lite-251015"))
    ark_base_url: str = field(
        default_factory=lambda: _env("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    )

    # 通用 OpenAI 兼容上游
    compat_base_url: str = field(default_factory=lambda: _env("COMPAT_BASE_URL"))
    compat_api_key: str = field(default_factory=lambda: _env("COMPAT_API_KEY"))
    compat_model: str = field(default_factory=lambda: _env("COMPAT_MODEL"))
    # DeepSeek 网页版（免 Key，逆向 chat.deepseek.com）
    # 完整 Cookie（推荐）：DEEPSEEK_COOKIE_1、DEEPSEEK_COOKIE_2 ... 支持多账号轮询
    deepseek_cookies: list[str] = field(default_factory=list)
    # 或直接填网页版 token（登录后浏览器里 Authorization: Bearer 后面那串）
    deepseek_token: str = field(default_factory=lambda: _env("DEEPSEEK_TOKEN"))
    # 可选：DeepSeek 官方 API Key（api.deepseek.com，按量计费；未配 Cookie 时兜底用）
    deepseek_api_key: str = field(default_factory=lambda: _env("DEEPSEEK_API_KEY"))
    # 网页版后端地址（默认 chat.deepseek.com，一般无需改；测试/代理时可覆盖）
    deepseek_web_base: str = field(
        default_factory=lambda: _env("DEEPSEEK_WEB_BASE", "https://chat.deepseek.com")
    )
    # 通义千问（阿里云百炼，官方 OpenAI 兼容，有每日免费 token 额度）
    qwen_api_key: str = field(default_factory=lambda: _env("QWEN_API_KEY"))
    qwen_base_url: str = field(
        default_factory=lambda: _env("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    )
    # 通义千问网页版（逆向 tongyi.aliyun.com，免 Key）
    # 完整 Cookie：QWEN_COOKIE_1、QWEN_COOKIE_2 ...（自动提取 tongyi_sso_ticket 作 Bearer）
    qwen_cookies: list[str] = field(default_factory=list)
    # 网页版后端地址（默认 qianwen.biz.aliyun.com，一般无需改；测试/代理时可覆盖）
    qwen_web_base: str = field(
        default_factory=lambda: _env("QWEN_WEB_BASE", "https://qianwen.biz.aliyun.com")
    )

    @property
    def doubao_web_enabled(self) -> bool:
        return bool(self.doubao_session_ids)

    @property
    def ark_enabled(self) -> bool:
        return bool(self.ark_api_key)

    @property
    def compat_enabled(self) -> bool:
        return bool(self.compat_base_url and self.compat_api_key)

    @property
    def deepseek_enabled(self) -> bool:
        """DeepSeek 通道可用：网页版 Cookie / token / 官方 Key 任一即可。"""
        return bool(self.deepseek_cookies or self.deepseek_token or self.deepseek_api_key)

    @property
    def qwen_enabled(self) -> bool:
        """通义千问通道可用：网页版 Cookie（免 Key）或百炼 API Key 任一即可。"""
        return bool(self.qwen_cookies or self.qwen_api_key)


def load_config() -> Config:
    cfg = Config()
    # 扫描 DOUBAO_COOKIE_1..N（完整 Cookie，多账号轮询）
    cookies: list[str] = []
    i = 1
    while True:
        val = _env(f"DOUBAO_COOKIE_{i}")
        if not val:
            break
        cookies.append(val)
        i += 1
    cfg.doubao_cookies = cookies
    # 扫描 DEEPSEEK_COOKIE_1..N（DeepSeek 网页版完整 Cookie，多账号轮询）
    ds_cookies: list[str] = []
    i = 1
    while True:
        val = _env(f"DEEPSEEK_COOKIE_{i}")
        if not val:
            break
        ds_cookies.append(val)
        i += 1
    cfg.deepseek_cookies = ds_cookies
    # 扫描 QWEN_COOKIE_1..N（通义千问网页版完整 Cookie，多账号轮询）
    qw_cookies: list[str] = []
    i = 1
    while True:
        val = _env(f"QWEN_COOKIE_{i}")
        if not val:
            break
        qw_cookies.append(val)
        i += 1
    cfg.qwen_cookies = qw_cookies
    return cfg
