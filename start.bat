@echo off
chcp 936 >nul
title SnapPaddleOCR 截图速识

:: 切换到脚本所在目录
cd /d "%~dp0"

:: 检测虚拟环境
if not exist ".venv\Scripts\python.exe" (
    echo [X] 未检测到虚拟环境，请先运行: python -m venv .venv
    echo     然后运行: .venv\Scripts\pip install -r paddle_ocr_tool\requirements.txt
    pause
    exit /b 1
)

:: 激活虚拟环境并启动
echo [*] 使用虚拟环境: .venv
.venv\Scripts\python.exe launcher.py

pause
