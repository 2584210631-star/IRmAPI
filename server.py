"""IRmAPI：一个类似 Chat2API、内置豆包的多通道 OpenAI 兼容网关。

入口文件：python app.py
控制台：http://<host>:<port>/console
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from gateway.config import Config, load_config
from gateway.models import ChatCompletionRequest
from gateway.response import build_error, encode_sse, finish_stream_sse
from gateway.routing import RoutingError, resolve_provider_key
from gateway.stats import get_stats
from gateway.tokens import TokenPool, _AuthError
from providers.registry import ProviderRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("irmapi")

# 全局单例（测试时可注入）
_app_state: dict[str, Any] = {"config": None, "registry": None, "tokens": None}
_config: Config = load_config()
_app_state["config"] = _config
_app_state["registry"] = ProviderRegistry(_config)
_app_state["tokens"] = TokenPool(_config)

app = FastAPI(title="IRmAPI", version="1.3.0", docs_url=None, redoc_url=None)

def _resource_path(rel: str) -> Path:
    """同时兼容源码运行与 PyInstaller 打包（onefile 资源在 sys._MEIPASS）。"""
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return Path(base) / rel


CONSOLE_HTML = _resource_path("console/index.html")


def _get_state() -> dict[str, Any]:
    return _app_state


def _console_allowed(request: Request) -> bool:
    """控制台访问口令校验：设置了 CONSOLE_KEY 时，/api/* 需要带 X-Console-Key。"""
    key = _get_state()["config"].console_key
    if not key:
        return True
    return request.headers.get("X-Console-Key") == key


# ---------- 基础 ----------
@app.get("/")
def index():
    return {
        "name": "IRmAPI",
        "desc": "类似 Chat2API 的多通道 OpenAI 兼容网关，内置豆包（网页版免Key + 火山方舟官方）",
        "console": "/console",
        "endpoints": ["/v1/models", "/v1/chat/completions", "/ping", "/api/status"],
    }


@app.get("/ping")
def ping():
    return {"status": "ok"}


@app.get("/console")
def console():
    if CONSOLE_HTML.exists():
        return FileResponse(CONSOLE_HTML)
    return JSONResponse(content={"error": "console/index.html 缺失"}, status_code=500)


# ---------- 状态接口（供控制台）----------
def _mask(value: str, head: int = 4, tail: int = 4) -> str:
    if len(value) <= head + tail:
        return value[:head] + "***"
    return f"{value[:head]}...{value[-tail:]}"


@app.get("/api/status")
def api_status(request: Request):
    if not _console_allowed(request):
        return JSONResponse(status_code=401, content={"error": "控制台口令错误"})
    cfg: Config = _get_state()["config"]
    cookies = cfg.doubao_cookies or []
    channels = [
        {
            "key": "doubao_web",
            "name": "豆包网页版",
            "desc": "免 Key，用浏览器 Cookie",
            "configured": bool(cookies or cfg.doubao_session_ids),
            "detail": f"{len(cookies)} 个完整 Cookie" if cookies else ("sessionid 模式" if cfg.doubao_session_ids else ""),
            "masked": [_mask(c.split("sessionid=")[-1].split(";")[0][:36]) for c in cookies[:3]],
        },
        {
            "key": "doubao_ark",
            "name": "豆包火山方舟",
            "desc": "官方 API，稳定有免费额度",
            "configured": cfg.ark_enabled,
            "detail": _mask(cfg.ark_api_key) if cfg.ark_enabled else "",
            "masked": [],
        },
        {
            "key": "openai_compat",
            "name": "通用 OpenAI 兼容",
            "desc": "Kimi / GLM / Ollama 等",
            "configured": cfg.compat_enabled,
            "detail": (cfg.compat_base_url or "").replace("/v1", "") if cfg.compat_enabled else "",
            "masked": [],
        },
        {
            "key": "deepseek_web",
            "name": "DeepSeek 网页版",
            "desc": "免 Key，用浏览器 Cookie / Token",
            "configured": cfg.deepseek_enabled,
            "detail": (
                f"{len(cfg.deepseek_cookies)} 个完整 Cookie" if cfg.deepseek_cookies
                else ("网页版 Token" if cfg.deepseek_token else ("官方 API Key" if cfg.deepseek_api_key else ""))
            ),
            "masked": [],
        },
        {
            "key": "qwen_api",
            "name": "通义千问",
            "desc": "网页版免 Key / 百炼官方免费额度",
            "configured": cfg.qwen_enabled,
            "detail": (
                f"网页版 {len(cfg.qwen_cookies)} 个 Cookie" if cfg.qwen_cookies
                else (_mask(cfg.qwen_api_key) if cfg.qwen_api_key else "")
            ),
            "masked": [],
        },
    ]
    models = _get_state()["registry"].list_models()
    return {
        "app": {"name": "IRmAPI", "version": "1.3.0", "host": cfg.host, "port": cfg.port},
        "channels": channels,
        "models": models,
        "stats": get_stats().snapshot(),
        "console_key_set": bool(cfg.console_key),
    }


# ---------- 调试代理（控制台 Playground，走服务端凭据）----------
@app.post("/api/playground")
async def api_playground(request: Request):
    if not _console_allowed(request):
        return JSONResponse(status_code=401, content={"error": "控制台口令错误"})
    state = _get_state()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content=build_error(400, "请求体不是合法 JSON"))

    model = body.get("model") or "doubao-web"
    messages = body.get("messages") or [{"role": "user", "content": "你好"}]
    stream = bool(body.get("stream", True))
    temperature = body.get("temperature")

    try:
        provider_key = resolve_provider_key(model, state["config"])
    except RoutingError as e:
        return JSONResponse(status_code=400, content=build_error(400, str(e)))
    provider = state["registry"].get(provider_key)

    kwargs: dict[str, Any] = {
        "temperature": temperature,
        "credential_mode": "server",
        "credential": "",
    }
    try:
        result = provider.chat(messages, model, stream=stream, **kwargs)
    except Exception as e:
        log.exception("playground provider 调用失败")
        code = getattr(e, "status_code", 502)
        return JSONResponse(status_code=code, content=build_error(code, str(e)))

    if stream and (hasattr(result, "__next__") or hasattr(result, "__iter__")):
        stats = get_stats()

        def gen():
            try:
                for chunk in result:
                    yield chunk
                stats.record(True)
            except Exception as e:
                stats.record(False, str(e))
                yield encode_sse(build_error(500, f"流式输出中断: {e}"))
                yield finish_stream_sse()

        return StreamingResponse(gen(), media_type="text/event-stream")
    if stream:
        return JSONResponse(status_code=500, content=build_error(500, "流式上游未返回流"))
    return JSONResponse(content=result)


# ---------- 重载配置（桌面版内置登录写入 .env 后免重启生效）----------
@app.post("/api/reload")
def api_reload(request: Request):
    if not _console_allowed(request):
        return JSONResponse(status_code=401, content={"error": "控制台口令错误"})
    try:
        cfg = load_config()
        _app_state["config"] = cfg
        _app_state["registry"] = ProviderRegistry(cfg)
        _app_state["tokens"] = TokenPool(cfg)
        return {"ok": True, "message": "配置已重载"}
    except Exception as e:
        log.exception("配置重载失败")
        return JSONResponse(status_code=500, content={"error": f"配置重载失败: {e}"})


# ---------- OpenAI 兼容接口 ----------
@app.get("/v1/models")
def list_models():
    models = _get_state()["registry"].list_models()
    data = [
        {"id": m, "object": "model", "created": 0, "owned_by": "irmapi"}
        for m in models
    ]
    return {"object": "list", "data": data}


@app.post("/v1/chat/completions")
def chat_completions(req: ChatCompletionRequest, request: Request):
    state = _get_state()
    auth_header = request.headers.get("Authorization")

    # 1. 解析凭据
    try:
        auth = state["tokens"].resolve(auth_header)
    except _AuthError as e:
        get_stats().record(False, str(e))
        return JSONResponse(status_code=401, content=build_error(401, str(e), "invalid_request_error"))

    # 2. 路由 provider
    try:
        provider_key = resolve_provider_key(req.model, state["config"])
    except RoutingError as e:
        get_stats().record(False, str(e))
        return JSONResponse(status_code=400, content=build_error(400, str(e), "invalid_request_error"))

    provider = state["registry"].get(provider_key)

    # 3. 转成 provider 需要的消息字典
    messages = [m.model_dump(exclude_none=True) for m in req.messages]

    # 4. 调用上游
    kwargs = {
        "temperature": req.temperature,
        "top_p": req.top_p,
        "max_tokens": req.max_tokens,
        "max_completion_tokens": req.max_completion_tokens,
        "user": req.user,
        "credential_mode": auth.mode,
        "credential": auth.credential,
    }
    try:
        result = provider.chat(messages, req.model, stream=req.stream, **kwargs)
    except Exception as e:
        log.exception("provider %s 调用失败", provider_key)
        code = getattr(e, "status_code", 502)
        get_stats().record(False, str(e))
        return JSONResponse(status_code=code, content=build_error(code, str(e)))

    # 5. 返回
    if req.stream:
        if hasattr(result, "__next__") or hasattr(result, "__iter__"):
            stats = get_stats()

            def gen():
                try:
                    for chunk in result:
                        yield chunk
                    stats.record(True)
                except Exception as e:
                    stats.record(False, str(e))
                    yield encode_sse(build_error(500, f"流式输出中断: {e}"))
                    yield finish_stream_sse()

            return StreamingResponse(gen(), media_type="text/event-stream")
        return JSONResponse(status_code=500, content=build_error(500, "流式上游未返回流"))

    get_stats().record(True)
    return JSONResponse(content=result)


def create_app(config: Config | None = None) -> FastAPI:
    """测试/可编程入口：传入自定义配置。"""
    if config is not None:
        _app_state["config"] = config
        _app_state["registry"] = ProviderRegistry(config)
        _app_state["tokens"] = TokenPool(config)
    return app


def main() -> None:
    import uvicorn

    cfg = _app_state["config"]
    enabled = [
        name
        for name, flag in [
            ("豆包网页版(免Key)", cfg.doubao_web_enabled),
            ("豆包火山方舟(官方)", cfg.ark_enabled),
            ("通用OpenAI兼容上游", cfg.compat_enabled),
            ("DeepSeek网页版(免Key)", cfg.deepseek_enabled),
            ("通义千问(网页版/百炼)", cfg.qwen_enabled),
        ]
        if flag
    ]
    log.info("IRmAPI 启动，可用通道: %s", enabled or ["无（请先在 .env 配置凭据）"])
    log.info("控制台: http://%s:%s/console", cfg.host, cfg.port)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
