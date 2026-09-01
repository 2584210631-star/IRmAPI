"""IRmAPI Android 版主程序（Kivy）—— 供 buildozer 打包成 APK。

功能与桌面版一致：
  1) 启动时后台拉起 FastAPI 网关（端口 5005）
  2) Kivy 原生界面：显示服务状态 + 三个按钮
     - 打开控制台：用 Android WebView 内嵌显示 http://127.0.0.1:5005/console
     - 一键登录豆包 / DeepSeek / 千问：Android WebView 打开登录页，
       登录成功后经 CookieManager 自动读取 Cookie 写入 .env 并热生效
  3) 关掉窗口即退出（网关随进程结束）

打包：`buildozer android debug`（详见 buildozer.spec 与 README）。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.clock import Clock

os.environ.setdefault("HOST", "127.0.0.1")
os.environ.setdefault("PORT", "5005")

_PORT = int(os.environ.get("PORT", "5005"))
_BASE_DIR = Path(__file__).resolve().parent


def run_gateway() -> None:
    import uvicorn
    from server import app

    uvicorn.run(app, host="127.0.0.1", port=_PORT, log_level="warning")


def wait_port(port: int, timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def reload_gateway() -> None:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{_PORT}/api/reload", method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def save_cookie(env_var: str, cookie_str: str) -> str:
    """把抓到的 Cookie 写入 .env（双引号包裹防截断），返回提示。"""
    env = _BASE_DIR / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    val = '"' + cookie_str.replace('"', '\\"') + '"'
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
    return f"{env_var} 已保存"


# ---------- Android WebView 登录（pyjnius） ----------
_LOGIN_SPECS = {
    "豆包": ("https://www.doubao.com/chat/", ("sessionid", "sessionid_ss"), "DOUBAO_COOKIE_1"),
    "DeepSeek": ("https://chat.deepseek.com/", ("token",), "DEEPSEEK_COOKIE_1"),
    "通义千问": ("https://tongyi.aliyun.com/", ("tongyi_sso_ticket", "login_aliyunid_ticket"), "QWEN_COOKIE_1"),
}


def android_webview_login(name: str) -> str:
    """在 Android 上用原生 WebView 打开登录页，登录后自动读 Cookie 存 .env。

    需要 python-for-android 的 android 模块（run_on_ui_thread）+ pyjnius。
    """
    try:
        from android import run_on_ui_thread
    except ImportError:
        return "当前环境无 android 模块（需在 APK 内运行）"
    url, success_keys, env_var = _LOGIN_SPECS[name]

    @run_on_ui_thread
    def _do_ui():
        from jnius import autoclass
        from android import activity

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        WebView = autoclass("android.webkit.WebView")
        WebViewClient = autoclass("android.webkit.WebViewClient")
        CookieManager = autoclass("android.webkit.CookieManager")
        LayoutParams = autoclass("android.view.ViewGroup$LayoutParams")
        LinearLayout = autoclass("android.widget.LinearLayout")
        Color = autoclass("android.graphics.Color")

        act = PythonActivity.mActivity
        layout = LinearLayout(act)
        layout.setBackgroundColor(Color.parseColor("#0b0e14"))
        wv = WebView(act)
        settings = wv.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)
        wv.setWebViewClient(WebViewClient())
        wv.loadUrl(url)
        layout.addView(wv, LayoutParams(-1, -1))
        act.setContentView(layout)

        def poll():
            deadline = time.time() + 600
            while time.time() < deadline:
                time.sleep(2)
                try:
                    cookie = CookieManager.getInstance().getCookie(url) or ""
                except Exception:
                    continue
                keys = {k.strip() for k, _v in [p.split("=", 1) for p in cookie.split(";") if "=" in p]}
                if not any(k in success_keys for k in keys):
                    continue
                msg = save_cookie(env_var, cookie)
                reload_gateway()
                try:
                    act.runOnUiThread(lambda: act.setContentView(PythonActivity.mContentView))
                except Exception:
                    pass
                return msg

        threading.Thread(target=poll, daemon=True).start()

    try:
        _do_ui()
    except Exception as e:
        return f"打开登录窗口失败: {e}"
    return f"已打开{name}登录窗口，登录成功后自动保存 Cookie 并生效"




class IrmUi(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=24, spacing=16, **kw)
        self.status = Label(
            text="IRmAPI 网关启动中…",
            font_size="20sp",
            size_hint_y=None,
            height=48,
            color=(0.75, 0.95, 0.93, 1),
        )
        self.add_widget(self.status)
        self.info = Label(
            text=f"端口 {_PORT} · 控制台 /console",
            font_size="14sp",
            size_hint_y=None,
            height=32,
            color=(0.5, 0.65, 0.7, 1),
        )
        self.add_widget(self.info)
        self.add_widget(Button(text="打开控制台", on_press=lambda *a: self.open_console()))
        self.add_widget(Button(text="一键登录豆包（自动抓 Cookie）", on_press=lambda *a: self.do_login("豆包")))
        self.add_widget(Button(text="一键登录 DeepSeek（自动抓 Cookie）", on_press=lambda *a: self.do_login("DeepSeek")))
        self.add_widget(Button(text="一键登录通义千问（自动抓 Cookie）", on_press=lambda *a: self.do_login("通义千问")))
        self.add_widget(Button(text="退出", on_press=lambda *a: App.get_running_app().stop()))
        Clock.schedule_once(self._tick, 0.5)

    def _tick(self, dt):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/ping", timeout=1)
            self.status.text = "IRmAPI 网关运行中 ✓"
        except Exception:
            self.status.text = "网关未就绪"
        Clock.schedule_once(self._tick, 3)

    def open_console(self):
        try:
            from android import activity
            from jnius import autoclass

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            WebView = autoclass("android.webkit.WebView")
            WebViewClient = autoclass("android.webkit.WebViewClient")
            LayoutParams = autoclass("android.view.ViewGroup$LayoutParams")

            act = PythonActivity.mActivity
            wv = WebView(act)
            wv.getSettings().setJavaScriptEnabled(True)
            wv.getSettings().setDomStorageEnabled(True)
            wv.setWebViewClient(WebViewClient())
            wv.loadUrl(f"http://127.0.0.1:{_PORT}/console")
            act.setContentView(wv)
        except Exception:
            import webbrowser

            webbrowser.open(f"http://127.0.0.1:{_PORT}/console")

    def do_login(self, name):
        msg = android_webview_login(name)
        self.status.text = msg


class IrmApiApp(App):
    def build(self):
        self.title = "IRmAPI"
        threading.Thread(target=run_gateway, daemon=True).start()
        threading.Thread(target=self._wait_and_report, daemon=True).start()
        return IrmUi()

    def _wait_and_report(self):
        ok = wait_port(_PORT)
        time.sleep(0.5)


if __name__ == "__main__":
    IrmApiApp().run()
