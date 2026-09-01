# -*- mode: python ; coding: utf-8 -*-
"""IRmAPI 桌面版 PyInstaller 打包配置。

用法（Windows）：  python -m PyInstaller --noconfirm IRmAPI.spec
产出：dist/IRmAPI.exe（单文件、无控制台黑窗、自带图标）
"""
from PyInstaller.utils.hooks import collect_all

# uvicorn/httpx/anyio 等动态 import 较多的包，显式收集，避免打包后运行报模块缺失
datas, binaries, hiddenimports = [], [], []
for pkg in ("uvicorn", "httpx", "anyio", "httpcore", "h11", "python_multipart", "dotenv",
            "setuptools", "pkg_resources"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass
# pkg_resources 运行时依赖 vendored appdirs（PyInstaller 新版 setuptools 的 hook 不兼容，
# 需手动收集 _vendor，否则打包产物启动即崩）
hiddenimports += ["appdirs", "pkg_resources._vendor.appdirs"]

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas + [("console/index.html", "console")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="IRmAPI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 无黑色控制台窗口，纯 GUI
    icon="resources/icon.ico",
    disable_windowed_traceback=False,
)
