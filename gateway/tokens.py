"""令牌池：解析 Authorization，支持客户端直传凭据 / 服务端账号池两种模式。"""
from __future__ import annotations

import random
from typing import Any

from gateway.config import Config


class AuthInfo:
    """解析结果。

    mode="server"：客户端命中了服务端授权码 -> 由 provider 使用服务端凭据池；
    mode="client"：客户端把凭据直接传给我们 -> provider 应直接使用 credential。
    """

    def __init__(self, mode: str, credential: str):
        self.mode = mode
        self.credential = credential

    def __repr__(self) -> str:  # 避免打印真实凭据
        return f"AuthInfo(mode={self.mode!r})"


class TokenPool:
    """解析 Authorization 请求头（规则对齐 Chat2API）：
      1. 命中服务端 AUTHORIZATION 授权码 -> 服务端凭据池（DOUBAO_COOKIE / ARK_KEY 等）。
      2. 否则把请求头里的 Bearer 值当作凭据本身（逗号分隔多账号随机轮询）。
      3. 都没有 -> 401。
    """

    def __init__(self, config: Config):
        self.config = config

    def resolve(self, authorization_header: str | None) -> AuthInfo:
        if not authorization_header:
            raise _AuthError("未提供 Authorization 请求头")

        token = authorization_header.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()

        # 模式 1：命中服务端授权码 -> 使用服务端账号池
        if self.config.authorization and token in self.config.authorization:
            return AuthInfo("server", token)

        # 模式 2：把客户端传入值当作凭据（逗号分隔多账号随机轮询）
        candidates = [t.strip() for t in token.split(",") if t.strip()]
        if candidates:
            return AuthInfo("client", random.choice(candidates))

        raise _AuthError("Authorization 为空")


class _AuthError(Exception):
    pass
