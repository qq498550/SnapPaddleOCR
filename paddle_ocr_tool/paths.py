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


def _resolve_cache_dir(project_root: str) -> str:
    """模型缓存目录

    打包后安装目录可能在 Program Files（无写权限），因此模型缓存
    放到用户目录 %LOCALAPPDATA%\\SnapPaddleOCR\\models；
    开发模式仍使用项目内 .paddlex_cache，便于复用已下载模型。
    """
    if not _FROZEN:
        return os.path.join(project_root, ".paddlex_cache")
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(local, "SnapPaddleOCR", "models")


TOOL_DIR = os.path.join(PROJECT_ROOT, "paddle_ocr_tool")
CACHE_DIR = _resolve_cache_dir(PROJECT_ROOT)
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")


def resource_path(relative):
    """获取资源文件的绝对路径（icon / config 等）"""
    return os.path.join(PROJECT_ROOT, relative)


def ensure_cache_dir() -> str:
    """确保模型缓存目录存在并返回其路径"""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
    except OSError:
        pass
    return CACHE_DIR
