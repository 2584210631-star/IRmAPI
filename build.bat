@echo off
chcp 65001 >nul
title IRmAPI 桌面版一键打包
echo ============================================
echo    IRmAPI 桌面版一键打包（生成 dist\IRmAPI.exe）
echo    Python 3.9+ 请先安装好，再双击本脚本
echo ============================================
echo [1/3] 安装依赖（含 pywebview / pyinstaller）
python -m pip install -r requirements.txt pywebview pyinstaller
if errorlevel 1 (echo 依赖安装失败，请检查网络或 Python 环境 & pause & exit /b 1)

echo [2/3] PyInstaller 打包（单文件、无黑窗、带图标，约 1-3 分钟）
python -m PyInstaller --noconfirm IRmAPI.spec
if errorlevel 1 (echo 打包失败，请看上方报错 & pause & exit /b 1)

echo [3/3] 完成！
echo --------------------------------------------
echo   可执行文件：dist\IRmAPI.exe
echo   直接双击运行，弹出的窗口就是软件界面（无需浏览器）。
echo   卸载 = 删除整个文件夹即可，无残留。
echo --------------------------------------------
pause
