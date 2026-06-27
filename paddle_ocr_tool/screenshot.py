# SnapPaddleOCR - 截图模块

from PIL import Image, ImageGrab


class ScreenCapture:
    """屏幕截图工具"""
    
    @staticmethod
    def capture_fullscreen():
        """捕获全屏截图"""
        return ImageGrab.grab(all_screens=True)
    
    @staticmethod
    def capture_region(bbox):
        """捕获指定区域
        
        Args:
            bbox: (left, top, right, bottom) 坐标元组
            
        Returns:
            PIL.Image: 区域截图
        """
        return ImageGrab.grab(bbox=bbox)
    
    @staticmethod
    def get_screen_size():
        """获取屏幕尺寸"""
        screen = ImageGrab.grab(all_screens=True)
        return screen.size


def capture_screenshot_region(main_window=None):
    """截图区域选择 - 便捷函数
    
    start_region_selection 现在直接返回裁剪好的 PIL.Image，
    覆盖层创建时已预先抓取全屏图，避免竞态条件。
    
    Args:
        main_window: MainWindow实例
        
    Returns:
        PIL.Image or None
    """
    if main_window and hasattr(main_window, 'start_region_selection'):
        return main_window.start_region_selection()
    return None
