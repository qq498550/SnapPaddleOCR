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
    # 关闭 PIR 新执行器（与 OneDNN 组合在部分 CPU 上报错）
    # 注意：FLAGS_use_mkldnn 由 OCR 引擎按用户配置在初始化时决定
    for key in (
        "FLAGS_enable_pir_api",
        "FLAGS_enable_pir_in_executor",
    ):
        os.environ.setdefault(key, "0")

    # 不跳过模型源连通性检查：首次运行需联网下载模型，
    # 跳过检查会按固定顺序尝试源，在部分网络环境下全部失败

    # 模型缓存目录（首次运行由 PaddleX 自动下载所选档位模型）
    if cache_dir is None:
        cache_dir = CACHE_DIR
    cache_dir = os.path.abspath(cache_dir)
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError:
        pass
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", cache_dir)


def apply_thread_env():
    """固定 OpenMP 线程数为 1，避免与 Paddle 线程池双重抢占核心

    必须在 paddle 首次导入前调用。Paddle 的 CPU 并行由
    set_cpu_math_library_num_threads（即 cpu_threads）控制，
    若 OMP_NUM_THREADS 同时设为 N，会额外创建一套 OpenMP 线程池，
    两套线程池互相争抢导致 CPU 占用上不去且识别显著变慢。
    实测（16 逻辑核 / 900x500 图）：OMP=1 耗时 8.0s，OMP=16 为 10.1s，
    OMP 未设置时 11.0s。
    """
    os.environ["OMP_NUM_THREADS"] = "1"


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
