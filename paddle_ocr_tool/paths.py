"""统一路径解析 — 兼容开发模式与 PyInstaller 打包模式"""
import os
import sys

_FROZEN = getattr(sys, 'frozen', False)

# 一级目录常量（仅在本模块计算一次，全局复用）
if _FROZEN:
    PROJECT_ROOT = sys._MEIPASS
else:
    PROJECT_ROOT = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )

TOOL_DIR = os.path.join(PROJECT_ROOT, "paddle_ocr_tool")
CACHE_DIR = os.path.join(PROJECT_ROOT, ".paddlex_cache")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")


def resource_path(relative):
    """获取资源文件的绝对路径（icon / config 等）"""
    return os.path.join(PROJECT_ROOT, relative)
