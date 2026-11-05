# SnapPaddleOCR - 截图模块

from typing import Any, Optional

from PIL import Image


def capture_screenshot_region(main_window: Optional[Any] = None) -> Optional[Image.Image]:
    """截图区域选择 - 便捷函数

    委托主窗口的 SelectionOverlay 冻结全屏画面并等待用户框选，
    直接返回裁剪好的 PIL.Image，覆盖层创建时已预先抓取全屏图，
    避免竞态条件。

    Args:
        main_window: MainWindow 实例

    Returns:
        PIL.Image，用户取消或不可用时返回 None
    """
    if main_window and hasattr(main_window, "start_region_selection"):
        return main_window.start_region_selection()
    return None
