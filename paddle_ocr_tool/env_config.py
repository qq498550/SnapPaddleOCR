"""
SnapPaddleOCR · 截图速识 - 统一环境变量配置
必须在任何 Paddle/PaddleOCR 导入前调用
"""
import os
import sys

from .paths import CACHE_DIR, PROJECT_ROOT


def setup_paddle_env(cache_dir=None):
    """设置 PaddleOCR 运行所需的环境变量

    Args:
        cache_dir: 模型缓存目录，默认使用 paths.CACHE_DIR
    """
    # 强制关闭 OneDNN，避免 PIR 新执行器在部分 CPU 上报错
    for key in (
        "FLAGS_use_mkldnn",
        "FLAGS_enable_pir_api",
        "FLAGS_enable_pir_in_executor",
    ):
        os.environ.setdefault(key, "0")

    # 禁用模型源检查
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

    # 模型缓存目录
    if cache_dir is None:
        cache_dir = CACHE_DIR
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", os.path.abspath(cache_dir))


def setup_dpi_awareness():
    """设置 Windows DPI 感知模式（必须在 tkinter 导入前调用）"""
    if sys.platform != "win32":
        return

    import ctypes

    try:
        # Win10 1703+: GDI 位图缩放
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-5)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(0)
        except Exception:
            pass


def ensure_sys_path():
    """确保项目根在 sys.path 中（仅父目录，保证包内相对导入正常）"""
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
