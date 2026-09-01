"""IRmAPI 手机（Pydroid 3）一键安装启动脚本 —— 不用 APK 也能在手机上跑。

用法（Pydroid 3 终端里）：
    pip install -r requirements.txt      # 安装依赖（也可直接运行本脚本，自动装）
    python setup_pydroid.py              # 一键启动

启动后手机浏览器打开 http://127.0.0.1:5005/console 即可使用。
Pydroid 模式没有「一键登录」按钮（无原生 WebView），请按控制台教程手动填 Cookie / Key。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

REQS = [
    "fastapi",
    "uvicorn",
    "httpx",
    "pydantic",
    "python-dotenv",
    "python-multipart",
]


def main() -> int:
    # 1. 确保依赖已装
    try:
        import fastapi  # noqa
        import uvicorn  # noqa
        import httpx  # noqa
        import pydantic  # noqa
        import dotenv  # noqa
    except ImportError:
        print("[IRmAPI] 正在安装依赖，请稍候…（首次约 1-2 分钟）")
        r = subprocess.run([sys.executable, "-m", "pip", "install"] + REQS)
        if r.returncode != 0:
            print("[IRmAPI] 依赖安装失败，请手动执行: pip install -r requirements.txt")
            return 1

    # 2. 启动网关
    print("[IRmAPI] 启动网关（端口 5005）…")
    import uvicorn
    from server import app

    port = int(os.environ.get("PORT", "5005"))

    import threading

    t = threading.Thread(
        target=uvicorn.run, args=(app,), kwargs={"host": "127.0.0.1", "port": port, "log_level": "warning"},
        daemon=True,
    )
    t.start()

    # 3. 等就绪
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1)
            break
        except Exception:
            time.sleep(0.2)

    print(f"[IRmAPI] 已就绪！请用手机浏览器打开:")
    print(f"           http://127.0.0.1:{port}/console")
    print("[IRmAPI] 关闭本窗口即停止服务。Ctrl+C 退出。")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[IRmAPI] 已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
