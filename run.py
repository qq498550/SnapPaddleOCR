"""SnapPaddleOCR · 直接启动入口（跳过依赖检测）"""
import sys
import os

# 确保项目根在 sys.path 中
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 打包产物自检模式（构建脚本调用，用于验证推理链路与精简结果）
if "--selftest" in sys.argv:
    from paddle_ocr_tool.selftest import run as run_selftest

    sys.exit(run_selftest())

from paddle_ocr_tool import __version__
from paddle_ocr_tool.main import main

if __name__ == "__main__":
    print(f"SnapPaddleOCR v{__version__} 启动中...")
    main()
