"""通义千问网页版（tongyi.aliyun.com）逆向 Provider —— 免 Key，用浏览器 Cookie。
原理（参照 qwen-free-api 社区成熟方案）：
  1) 登录 https://tongyi.aliyun.com，从浏览器抓【完整 Cookie】。
  2) 从 Cookie 提取 `tongyi_sso_ticket`（或阿里云 `login_aliyunid_ticket`）作为鉴权票据。
  3) 用 Cookie 调网页版后端 POST /dialog/conversation（qianwen.biz.aliyun.com）。
  4) 把网页版流式响应转换成标准 OpenAI 格式返回。
凭据：
  - QWEN_COOKIE_1=...（完整 Cookie，推荐；会自动提取 tongyi_sso_ticket）
  - 支持 QWEN_COOKIE_2..N 多账号轮询
  桌面版用户可在控制台凭据页点「一键登录千问（网页版）」自动抓取，无需手动 F12。
注意：逆向接口依赖通义千问前端，改版可能失效；仅供个人学习自用。
"""
from __future__ import annotations
import json
import random
import re
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
from providers.base import BaseProvider, ProviderError
QWEN_DEFAULT_MODEL = "qwen-turbo"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
# 与 qwen-free-api 一致的伪装头
_FAKE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Origin": "https://tongyi.aliyun.com",
    "Referer": "https://tongyi.aliyun.com/",
    "User-Agent": _UA,
    "X-Platform": "pc_tongyi",
    "X-Xsrf-Token": "48b9ee49-a184-45e2-9f67-fa87213edcdc",
}


class QwenWebProvider(BaseProvider):
    key = "qwen_web"
    label = "通义千问网页版（免 Key / 浏览器 Cookie）"

    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0))

    # ---------- 凭据 ----------
    @staticmethod
    def _extract_ticket(cookie: str) -> str:
        for part in cookie.split(";"):
            part = part.strip()
            name = part.split("=", 1)[0].strip().lower()
            if name in ("tongyi_sso_ticket", "login_aliyunid_ticket"):
                return part.split("=", 1)[1].strip()
        return ""

    def _credentials(self) -> list[dict[str, str]]:
        creds: list[dict[str, str]] = []
        for c in self.config.qwen_cookies:
            ticket = self._extract_ticket(c)
            if ticket:
                creds.append({"cookie": c, "ticket": ticket})
        if not creds:
            raise ProviderError(
                "通义千问网页版通道未配置凭据：请填 QWEN_COOKIE_1（登录 tongyi.aliyun.com 后抓的完整 Cookie），"
                "或改用 QWEN_API_KEY（阿里云百炼，官方免费额度）",
                401,
            )
        return creds

    @staticmethod
    def _make_cookie(ticket: str) -> str:
        # ticket 长则视为阿里云 login_aliyunid_ticket，否则视为 tongyi_sso_ticket
        name = "login_aliyunid_ticket" if len(ticket) > 100 else "tongyi_sso_ticket"
        return (
            f"{name}={ticket}; aliyun_choice=intl; "
            f"_samesite_flag_=true; t={uuid.uuid4().hex}"
        )

    # ---------- 消息 ----------
    @staticmethod
    def _to_content(messages: list[dict[str, Any]], with_roles: bool) -> str:
        parts: list[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        texts.append(str(item.get("text", "")))
                content = "\n".join(texts)
            content = str(content)
            if with_roles:
                parts.append(f"<|im_start|>{role}\n{content}<|im_end|>\n")
            else:
                parts.append(content + "\n")
        joined = "".join(parts)
        # 去掉 markdown 图片语法（网页版不接受）
        return re.sub(r"!\[.*?\]\(.+?\)", "", joined)

    def _payload(
        self, messages: list[dict[str, Any]], ref_conv: str = ""
    ) -> dict[str, Any]:
        session_id = ""
        parent_msg_id = ""
        if ref_conv and "-" in ref_conv:
            session_id, parent_msg_id = ref_conv.split("-", 1)
        # 单轮（<2 条）直接透传内容；多轮用 ChatML 拼接，保持上下文
        with_roles = len(messages) >= 2
        return {
            "mode": "chat",
            "model": "",
            "action": "next",
            "userAction": "chat",
            "requestId": uuid.uuid4().hex,
            "sessionId": session_id,
            "sessionType": "text_chat",
            "parentMsgId": parent_msg_id,
            "params": {"fileUploadBatchId": uuid.uuid4().hex},
            "contents": [
                {"content": self._to_content(messages, with_roles), "contentType": "text", "role": "user"}
            ],
        }

    # ---------- 请求 ----------
    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = False,
        **kwargs: Any,
    ) -> Iterator[str] | dict[str, Any]:
        cred = random.choice(self._credentials())
        headers = {
            "Content-Type": "application/json",
            "Cookie": self._make_cookie(cred["ticket"]),
            **(_FAKE_HEADERS if self.config.qwen_web_base.startswith("https://qianwen") else {}),
            "Accept": "text/event-stream",
        }
        payload = self._payload(messages)
        try:
            resp = self.client.post(
                f"{self.config.qwen_web_base}/dialog/conversation",
                headers=headers,
                json=payload,
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"连接通义千问网页版失败: {e}", 502)
        if resp.status_code != 200:
            raise ProviderError(
                f"通义千问网页版返回 HTTP {resp.status_code}: {resp.text[:300]}"
                "（Cookie 可能已过期，或网页版接口已改版；可改用 QWEN_API_KEY 百炼通道）",
                502,
            )
        if stream:
            return self._forward_stream(resp, model)
        return self._forward_non_stream(resp, model)

    # ---------- 转发 ----------
    def _iter_qwen_events(self, resp: httpx.Response):
        """解析 qwen 网页版 SSE：data 行是 JSON，含 contents 增量。"""
        buffer = ""
        for raw in resp.iter_text():
            buffer += raw
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    yield json.loads(data)
                except Exception:
                    continue

    def _forward_stream(self, resp: httpx.Response, model: str) -> Iterator[str]:
        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
        yield build_start_chunk(chunk_id, model)
        acc_len = 0
        try:
            for ev in self._iter_qwen_events(resp):
                text = self._event_text(ev)
                if not text:
                    continue
                # 增量输出（网页版每次都回累计全文，需要截断）
                if len(text) > acc_len:
                    chunk = text[acc_len:]
                    acc_len = len(text)
                    if chunk:
                        yield build_content_chunk(chunk_id, model, chunk)
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"解析通义千问网页版响应流失败: {e}", 502)
        yield build_stop_chunk(chunk_id)
        yield finish_stream_sse()

    @staticmethod
    def _event_text(ev: dict[str, Any]) -> str:
        """从网页版事件里提取 assistant 文本（每次为累计全文）。"""
        text = ""
        for part in ev.get("contents") or []:
            if part.get("contentType") not in ("text", "text2image"):
                continue
            if part.get("role") != "assistant" or not isinstance(part.get("content"), str):
                continue
            text += part["content"]
        return text

    def _forward_non_stream(self, resp: httpx.Response, model: str) -> dict[str, Any]:
        # 网页版非流式实际也是 SSE 流，取最后一次完整全文
        full = ""
        for ev in self._iter_qwen_events(resp):
            text = self._event_text(ev)
            if text:
                full = text
        return build_final(
            f"chatcmpl-{uuid.uuid4().hex}",
            model,
            full,
            prompt_tokens=0,
            completion_tokens=0,
        )
