"""IRmAPI 桌面版：网关 + 原生桌面窗口，双击即用，无需开浏览器。

打包入口（Windows 上双击 build.bat 生成 dist/IRmAPI.exe）。
无图形环境可用 `python desktop.py --check` 只验证网关与资源，方便调试。

内置「一键登录豆包」：
  控制台凭据页点击按钮 -> 调本文件的 ConsoleApi.doubao_login()
  -> 弹出豆包登录窗口，登录完成后自动提取 Cookie 写入 .env 并热生效。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

_BASE_DIR = Path(__file__).resolve().parent
_LOGIN_TIMEOUT = 10 * 60  # 登录窗口超时（秒）


def resource_path(rel: str) -> str:
    """兼容 PyInstaller 打包后的资源路径（onefile 下资源在 sys._MEIPASS）。"""
    base = getattr(sys, "_MEIPASS", str(_BASE_DIR))
    return os.path.join(base, rel)


def run_gateway(host: str, port: int) -> None:
    """后台线程里跑 FastAPI 网关。"""
    import uvicorn
    from server import app
    uvicorn.run(app, host=host, port=port, log_level="warning")


def wait_port(port: int, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1)
            return True
        except Exception:
            time.sleep(0.15)
    return False


class ConsoleApi:
    """暴露给控制台页面的 Python 方法（页面里 window.pywebview.api.xxx 调用）。"""

    def __init__(self) -> None:
        self.port = int(os.environ.get("PORT", "5005"))

    # ---------- 一键登录（豆包 / DeepSeek / 通义千问） ----------
    def doubao_login(self) -> str:
        return self._start_login(
            "豆包",
            "https://www.doubao.com/chat/",
            ("sessionid", "sessionid_ss"),
            "DOUBAO_COOKIE_1",
        )

    def deepseek_login(self) -> str:
        return self._start_login(
            "DeepSeek",
            "https://chat.deepseek.com/",
            ("token",),
            "DEEPSEEK_COOKIE_1",
        )

    def qwen_login(self) -> str:
        return self._start_login(
            "通义千问",
            "https://tongyi.aliyun.com/",
            ("tongyi_sso_ticket", "login_aliyunid_ticket"),
            "QWEN_COOKIE_1",
        )

    def _start_login(self, name: str, url: str, success_keys: tuple, env_var: str) -> str:
        """后台打开登录窗口，检测到登录态后自动抓 Cookie 写入 .env 并热生效。"""
        threading.Thread(
            target=self._open_login_window,
            args=(name, url, success_keys, env_var),
            daemon=True,
        ).start()
        return (
            f"已在桌面版中打开「{name}」登录窗口：请用手机扫码或账号密码登录。"
            "登录成功后会自动保存 Cookie（" + env_var + "）并生效，无需手动复制。"
        )

    def _open_login_window(self, name: str, url: str, success_keys: tuple, env_var: str) -> None:
        import webview

        login_win: Any = None
        state = {"done": False}

        def poll() -> None:
            deadline = time.time() + _LOGIN_TIMEOUT
            while time.time() < deadline and not state["done"]:
                time.sleep(2)
                if login_win is None:
                    continue
                try:
                    cookies = login_win.get_cookies()
                except Exception:
                    continue
                if not cookies:
                    continue
                # 检测到对应通道的登录态（出现指定 cookie 即认为已登录）
                has_login = any(
                    c.get("name") in success_keys and c.get("value")
                    for c in cookies
                )
                if not has_login:
                    continue
                pairs = []
                for c in cookies:
                    v = c.get("value")
                    if v:
                        pairs.append(f"{c.get('name')}={v}")
                if not pairs:
                    continue
                state["done"] = True
                msg = self._save_env_cookie("; ".join(pairs), env_var=env_var)
                self._reload_gateway()
                try:
                    login_win.destroy()
                except Exception:
                    pass
                print(f"[IRmAPI] {msg}")
                return
            if not state["done"]:
                print(f"[IRmAPI] {name} 登录超时，已关闭登录窗口")
                try:
                    login_win.destroy()
                except Exception:
                    pass

        time.sleep(0.3)
        try:
            login_win = webview.create_window(
                f"登录{name}",
                url,
                width=1020,
                height=780,
                background_color="#0b0e14",
            )
            threading.Thread(target=poll, daemon=True).start()
        except Exception as e:
            print(f"[IRmAPI] 打开登录窗口失败: {e}")

    # ---------- 保存 Cookie 到 .env 并热生效 ----------
    def _save_env_cookie(
        self, cookie_str: str, env_path: Path | None = None, env_var: str = "DOUBAO_COOKIE_1"
    ) -> str:
        env = env_path or (_BASE_DIR / ".env")
        lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
        # 用双引号包裹，避免 cookie 里的空格/分号被 dotenv 截断
        val = '"' + cookie_str.replace('"', '\"') + '"'
        out: list[str] = []
        replaced = False
        for ln in lines:
            if ln.lstrip().startswith(env_var + "="):
                out.append(f"{env_var}={val}")
                replaced = True
            else:
                out.append(ln)
        if not replaced:
            out.append(f"{env_var}={val}")
        env.write_text("\n".join(out) + "\n", encoding="utf-8")
        return f"登录成功！Cookie 已保存到 .env（{env_var}）并已热生效。"

    def _reload_gateway(self) -> None:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/reload", method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass


def main() -> int:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5005"))

    # 1. 后台启动网关
    threading.Thread(target=run_gateway, args=(host, port), daemon=True).start()
    if not wait_port(port):
        print(f"[IRmAPI] 网关启动失败（端口 {port} 可能被占用，可在 .env 改 PORT）")
        return 1

    # 2. 无图形验证模式（CI / 沙箱 / 排障用）
    if "--check" in sys.argv:
        ok = os.path.exists(resource_path("console/index.html"))
        print(f"[IRmAPI] 网关正常；控制台资源存在: {ok}")
        return 0 if ok else 1

    # 3. 原生桌面窗口（pywebview，Windows 用系统自带 WebView2，体积小）
    import webview
    window = webview.create_window(
        "IRmAPI",
        f"http://127.0.0.1:{port}/console",
        width=1280,
        height=820,
        min_size=(1000, 660),
        background_color="#0b0e14",
        js_api=ConsoleApi(),
    )
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
