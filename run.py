"""SnapPaddleOCR · 直接启动入口（跳过依赖检测）"""
import sys
import os

# 确保项目根在 sys.path 中
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 环境变量已由 env_config.py 统一管理，这里重复确保
os.environ.setdefault("PADDLE_PDX_CACHE_HOME",
                      os.path.join(_project_root, ".paddlex_cache"))

from paddle_ocr_tool import __version__
from paddle_ocr_tool.main import main

if __name__ == "__main__":
    print(f"SnapPaddleOCR v{__version__} 启动中...")
    main()
