# IRmAPI 的 buildozer 配置 —— 一键把整个项目打包成 Android APK。
#
# 构建方式（任选其一，推荐 GitHub Actions，见 .github/workflows/build-apk.yml）：
#   1) 本地：装好 buildozer 后在此目录运行  buildozer android debug
#   2) 云端：把项目推到 GitHub，Actions 会自动构建并产出 bin/*.apk
#
# 说明：
#   - 入口是 main.py（Kivy），启动后自动拉起 FastAPI 网关（端口 5005）
#   - 界面提供「打开控制台 / 一键登录豆包·DeepSeek·千问」，登录自动抓 Cookie
#   - APK 里的「一键登录」用 Android 原生 WebView，首次请在真机上验证一次

[app]

# 应用名（桌面显示）
title = IRmAPI

# 包名
package.name = irmapi
package.domain = org.irm

# 源码目录（项目根）
source.dir = .

# 只打包需要的扩展名；html 是控制台单文件
source.include_exts = py,html

# 排除不需要进 APK 的目录
source.exclude_dirs = tests,dist,.git,__pycache__,.pytest_cache,.github,.tmp_qf

# 版本号（与 server.py 保持一致）
version = 1.3.0

# 依赖：python3 + kivy + 网关所需包
# 注意：kivy 请用最新稳定版；fastapi/uvicorn/pydantic 由 p4a 的 pip 安装
requirements = python3,kivy,pyjnius,android,fastapi,uvicorn,httpx,pydantic,python-dotenv

# 竖屏 / 全屏
orientation = portrait
fullscreen = 0

# 应用图标（IRm 艺术字，512x512）
icon.filename = resources/icon.png

# 权限：联网即可
android.permissions = INTERNET,ACCESS_NETWORK_STATE
# 允许明文 HTTP（本地网关 http://127.0.0.1:5005，Android 9+ 默认禁止）
android.usescleartexttraffic = True

# SDK / NDK 版本
android.api = 33
android.minapi = 21
android.ndk = 25b
# 自动接受 SDK 许可证（否则弹窗导致 build-tools 装不上）
android.accept_sdk_license = True

# 只打 arm64（主流手机）；如需兼容 32 位老机再加 armeabi-v7a
android.archs = arm64-v8a

android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
