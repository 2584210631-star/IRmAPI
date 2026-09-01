"""豆包网页版（www.doubao.com）逆向 Provider —— 忠实于真实浏览器抓包。

原理（与 Chat2API 用 ChatGPT accessToken 同理）：
  1) 登录豆包网页版，从浏览器里拿到【完整 Cookie】（含 sessionid / ttwid / 设备验证 cookie）。
  2) 用该 Cookie + 浏览器指纹（device_id/web_id/msToken/a_bogus）构造请求，
     打到豆包网页版后端 /samantha/chat/completion。
  3) 把返回的自定义 SSE 流（event_type 2001/2002/2003）转成 OpenAI 格式。

签名说明（重要）：
  - 纯“假签名”在部分网络/地区可用（社区 doubao-free-api 方案），但豆包随时会收紧风控。
  - 被 400/403 拒绝时，在 .env 填上从浏览器抓到的真实 DOUBAO_MS_TOKEN / DOUBAO_A_BOGUS，
    或开启 DOUBAO_SIGN_ENABLED 走内置 Playwright 实时签名。
"""
from __future__ import annotations

import json
import random
import string
import time
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

# ---- 豆包网页版后端常量（改版时主要改这里）----
DOUBAO_BASE = "https://www.doubao.com"
CHAT_ENDPOINT = "/samantha/chat/completion"
DELETE_ENDPOINT = "/samantha/thread/delete"

# 完整请求参数（来自浏览器抓包，保持与真实请求一致）
BASE_PARAMS = {
    "aid": "497858",
    "device_platform": "web",
    "language": "zh",
    "pc_version": "2.41.0",
    "pkg_type": "release_version",
    "real_aid": "497858",
    "region": "CN",
    "samantha_web": "1",
    "sys_region": "CN",
    "use-olympus-account": "1",
    "version_code": "20800",
}

# 与真实浏览器一致的请求头
FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": DOUBAO_BASE,
    "Referer": f"{DOUBAO_BASE}/chat/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    ),
    "agw-js-conv": "str, str",
    "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# 多轮消息合并用的角色标记（豆包网页版把历史拼进单条消息）
IM_START = "<|im_start|>"
IM_END = "<|im_end|>"


def _rand_digits(n: int) -> str:
    return "".join(random.choices(string.digits, k=n))


def _rand_base64url(n: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits + "-_", k=n))


class DoubaoWebProvider(BaseProvider):
    key = "doubao_web"
    label = "豆包网页版（免 Key / 浏览器 Cookie）"

    def __init__(self, config: Config):
        self.config = config
        self.device_id = config.doubao_device_id or _rand_digits(19)
        self.web_id = config.doubao_web_id or _rand_digits(19)
        self.client = httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0))

    # ---------- 凭据 ----------
    def _credentials(self) -> list[str]:
        """返回 Cookie 凭据列表（完整 Cookie 优先，sessionid 兜底合成）。"""
        cookies = self.config.doubao_cookies
        if cookies:
            return cookies
        sids = self.config.doubao_session_ids
        if sids:
            return [self._synth_cookie(s) for s in sids]
        raise ProviderError(
            "豆包网页版通道未配置凭据：请在 .env 填 DOUBAO_COOKIE_1（完整 Cookie，推荐）"
            "或 DOUBAO_SESSIONIDS（仅 sessionid）",
            401,
        )

    def _synth_cookie(self, session_id: str) -> str:
        now = int(time.time())
        uid = str(uuid.uuid4()).replace("-", "")
        return (
            f"sessionid={session_id}; sessionid_ss={session_id}; "
            f"sid_tt={session_id}; sid_guard={session_id}|{now}|2592000|0; "
            f"uid_tt={uid}; uid_tt_ss={uid}; "
            f"is_staff_user=false; store-region=cn-gd; store-region-src=uid"
        )

    # ---------- 签名 ----------
    def _ms_token(self) -> str:
        if self.config.doubao_ms_token:
            return self.config.doubao_ms_token
        return _rand_base64url(128)

    def _a_bogus(self) -> str:
        if self.config.doubao_a_bogus:
            return self.config.doubao_a_bogus
        return "mf-" + _rand_base64url(34) + "-" + _rand_base64url(6)

    def _build_query(self) -> dict[str, str]:
        """构造 URL 查询参数（含设备指纹与签名）。"""
        params = dict(BASE_PARAMS)
        params.update(
            {
                "device_id": self.device_id,
                "fp": _rand_base64url(20),
                "web_id": self.web_id,
                "tea_uuid": self.web_id,
                "web_tab_id": str(uuid.uuid4()),
                "msToken": self._ms_token(),
            }
        )
        params["a_bogus"] = self._a_bogus()
        return params

    # ---------- 消息转换 ----------
    @staticmethod
    def _content_to_text(content: Any) -> str:
        """把 OpenAI 的 content（str 或分段列表）转成纯文本。"""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                    # image_url / file 在 v1 暂不支持，跳过
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(p for p in parts if p)
        return str(content)

    def _prepare_text(self, messages: list[dict[str, Any]]) -> str:
        """把多轮 messages 合并为单段文本（豆包网页版要求单条消息）。"""
        if not messages:
            raise ProviderError("messages 不能为空", 400)
        if len(messages) == 1:
            return self._content_to_text(messages[0].get("content"))
        blocks: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            text = self._content_to_text(msg.get("content"))
            if not text:
                continue
            blocks.append(f"{IM_START}{role}\n{text}{IM_END}")
        return "\n".join(blocks)

    # ---------- 请求体 ----------
    @staticmethod
    def _build_payload(text: str, conversation_id: str) -> dict[str, Any]:
        return {
            "messages": [
                {
                    "content": json.dumps({"text": text}, ensure_ascii=False),
                    "content_type": 2001,  # 数字类型：text
                    "attachments": [],
                    "references": [],
                }
            ],
            "completion_option": {
                "is_regen": False,
                "with_suggest": True,
                "need_create_conversation": conversation_id == "0",
                "launch_stage": 1,
                "is_replace": False,
                "is_delete": False,
                "message_from": 0,
                "action_bar_skill_id": 0,
                "use_deep_think": False,
                "use_auto_cot": True,
                "resend_for_regen": False,
                "enable_commerce_credit": False,
                "event_id": "0",
            },
            "evaluate_option": {"web_ab_params": ""},
            "conversation_id": conversation_id,
            "local_conversation_id": f"local_{uuid.uuid4().hex}",
            "local_message_id": str(uuid.uuid4()),
        }

    def _chat_request(
        self,
        cookie: str,
        text: str,
        conversation_id: str,
        query: dict[str, str],
        timeout: int = 300,
    ) -> httpx.Response:
        headers = {
            **FAKE_HEADERS,
            "Cookie": cookie,
            "X-Flow-Trace": str(uuid.uuid4()),
        }
        return self.client.post(
            DOUBAO_BASE + CHAT_ENDPOINT,
            params=query,
            headers=headers,
            json=self._build_payload(text, conversation_id),
            timeout=timeout,
        )

    # ---------- 响应解析（豆包自定义 SSE）----------
    @staticmethod
    def _parse_event_data(data: dict[str, Any]) -> dict[str, Any]:
        """event_data 字段是一个 JSON 字符串，解析成 dict。"""
        ed = data.get("event_data")
        if isinstance(ed, str):
            try:
                return json.loads(ed)
            except json.JSONDecodeError:
                return {}
        return ed if isinstance(ed, dict) else {}

    @staticmethod
    def _extract_delta(data: dict[str, Any]) -> str:
        """从 event_type=2001 的 data 中取出文本增量。

        真实结构：data.event_data(JSON字符串) -> {message:{content:"JSON"}} -> {text}
        """
        try:
            event_data = DoubaoWebProvider._parse_event_data(data)
            message = event_data.get("message") or {}
            content = message.get("content") or ""
            if isinstance(content, str):
                obj = json.loads(content)
                if isinstance(obj, dict):
                    return str(obj.get("text", obj.get("content", "")) or "")
                return str(obj)
            if isinstance(content, dict):
                return str(content.get("text", content.get("content", "")) or "")
        except (json.JSONDecodeError, AttributeError):
            pass
        return ""

    @staticmethod
    def _extract_conversation_id(data: dict[str, Any]) -> str:
        """从 event_type=2002 的 data 中取出会话 id。"""
        ed = DoubaoWebProvider._parse_event_data(data)
        cid = ed.get("conversation_id") or ed.get("id") or ""
        return str(cid) if cid else ""

    def _raise_if_error(self, data: dict[str, Any]) -> None:
        code = data.get("code")
        msg = data.get("message") or data.get("msg") or ""
        # 豆包网关把业务错误放在 SSE 里返回（如 gateway-error）
        if "user invalid" in str(msg) or "710012000" in str(msg) or "Invalid User" in str(msg):
            raise ProviderError(
                "豆包提示 Cookie 无效或已过期（user invalid）。"
                "请重新登录 https://www.doubao.com 并更新 .env 里的 Cookie。",
                401,
            )
        if code not in (None, 0, "0", 200):
            raise ProviderError(f"{msg} (code={code})", 502)

    # ---------- 主入口 ----------
    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = False,
        credential_mode: str = "server",
        credential: str = "",
        **kwargs: Any,
    ) -> Iterator[str] | dict[str, Any]:
        text = self._prepare_text(messages)

        # 凭据选择：
        #  mode="client" -> 直接用客户端传的凭据（完整 Cookie 原样，否则当 sessionid 合成）
        #  mode="server" -> 用服务端配置的账号池（DOUBAO_COOKIE_1..N / DOUBAO_SESSIONIDS）
        if credential_mode == "client" and credential:
            if "sessionid=" in credential or ";" in credential or "ttwid=" in credential:
                credentials = [credential]
            else:
                credentials = [self._synth_cookie(credential)]
        else:
            credentials = self._credentials()

        retry = max(1, self.config.doubao_retry)

        last_err: Exception | None = None
        for _ in range(retry):
            cookie = random.choice(credentials)
            query = self._build_query()
            try:
                resp = self._chat_request(cookie, text, conversation_id="0", query=query)
                if resp.status_code != 200:
                    raise ProviderError(
                        f"豆包网页版返回 HTTP {resp.status_code}（常见原因：Cookie 过期 / "
                        f"签名被风控 / IP 受限）。请尝试在 .env 填入真实 msToken/a_bogus，"
                        f"或更新 Cookie。响应: {resp.text[:150]}",
                        502,
                    )
                if stream:
                    return self._stream(resp, cookie)
                return self._non_stream(resp, cookie)
            except ProviderError:
                raise
            except Exception as e:
                last_err = e
                continue
        raise ProviderError(f"豆包网页版请求失败（已重试 {retry} 次）: {last_err}", 502)

    def _delete_conversation(self, cookie: str, conversation_id: str) -> None:
        """请求结束后删除会话，避免出现在用户豆包聊天记录里。"""
        try:
            headers = {**FAKE_HEADERS, "Cookie": cookie}
            self.client.post(
                DOUBAO_BASE + DELETE_ENDPOINT,
                params=self._build_query(),
                headers=headers,
                json={"conversation_id": conversation_id},
                timeout=15.0,
            )
        except Exception:
            pass

    def _stream(self, resp: httpx.Response, cookie: str) -> Iterator[str]:
        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
        yield build_start_chunk(chunk_id, "doubao-web")
        conversation_id = ""
        text_done = False
        buffer = ""
        try:
            for raw in resp.iter_text():
                buffer += raw
                for event in iter_sse_events(buffer):
                    if event.get("_done"):
                        continue
                    self._raise_if_error(event)
                    et = event.get("event_type")
                    if et in (2002, "2002") and not conversation_id:
                        conversation_id = self._extract_conversation_id(event)
                    elif et in (2001, "2001"):
                        delta = self._extract_delta(event)
                        if delta:
                            yield build_content_chunk(chunk_id, "doubao-web", delta)
                    elif et in (2003, "2003"):
                        if not text_done:
                            text_done = True
                            yield build_stop_chunk(chunk_id, "doubao-web")
                buffer = ""
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"解析豆包响应流失败: {e}", 502)

        if not text_done:
            yield build_stop_chunk(chunk_id, "doubao-web")
        yield finish_stream_sse()

        if conversation_id and self.config.doubao_clean_conversation:
            self._delete_conversation(cookie, conversation_id)

    def _non_stream(self, resp: httpx.Response, cookie: str) -> dict[str, Any]:
        full: list[str] = []
        conversation_id = ""
        buffer = ""
        for raw in resp.iter_text():
            buffer += raw
            for event in iter_sse_events(buffer):
                self._raise_if_error(event)
                et = event.get("event_type")
                if et in (2002, "2002") and not conversation_id:
                    conversation_id = self._extract_conversation_id(event)
                elif et in (2001, "2001"):
                    delta = self._extract_delta(event)
                    if delta:
                        full.append(delta)
            buffer = ""
        content = "".join(full).rstrip("\n")
        result = build_final(f"chatcmpl-{uuid.uuid4().hex}", "doubao-web", content)

        if conversation_id and self.config.doubao_clean_conversation:
            self._delete_conversation(cookie, conversation_id)
        return result
