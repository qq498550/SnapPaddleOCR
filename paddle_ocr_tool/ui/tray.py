import os
import threading
import logging

from ..paths import resource_path

logger = logging.getLogger("SnapPaddleOCR.Tray")


class SystemTray:
    """系统托盘管理器"""
    
    def __init__(self):
        self._icon = None
        self._callbacks = {}
        self._running = False
        self._thread = None
    
    def init(self, app_name="SnapPaddleOCR"):
        """初始化系统托盘"""
        self._app_name = app_name
        if self._check_pystray():
            self._running = True
            return True
        return False
    
    def _check_pystray(self):
        try:
            import pystray
            return True
        except ImportError:
            return False
    
    def run(self, on_show=None, on_ocr=None, on_quit=None, on_clipboard_ocr=None):
        """启动托盘"""
        import os
        import pystray
        from PIL import Image
        
        self._callbacks = {
            "show": on_show,
            "ocr": on_ocr,
            "clipboard_ocr": on_clipboard_ocr,
            "quit": on_quit,
        }
        
        # 加载程序图标
        ico_path = resource_path("paddle_ocr_tool/ui/main.ico")
        if os.path.exists(ico_path):
            img = Image.open(ico_path)
        else:
            # 回退：生成简单图标
            icon_size = 32
            img = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 0))
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.ellipse([2, 2, icon_size-2, icon_size-2], fill="#2196F3")
            draw.text((5, 4), "O", fill="white", font=None)
        
        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", lambda: self._call("show"), default=True),
            pystray.MenuItem("截图OCR", lambda: self._call("ocr")),
            pystray.MenuItem("剪贴板OCR", lambda: self._call("clipboard_ocr")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self._call("quit")),
        )
        
        self._icon = pystray.Icon(self._app_name, img, self._app_name, menu)
        
        # 在后台线程运行托盘
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        self._running = True
    
    def _call(self, name):
        """调用回调"""
        cb = self._callbacks.get(name)
        if cb:
            cb()
    
    def notify(self, title, message, duration=5):
        """显示通知"""
        if self._icon:
            try:
                self._icon.notify(message, title)
            except Exception as e:
                logger.warning(f"通知失败: {e}")
    
    def stop(self):
        """停止托盘"""
        if self._icon:
            try:
                self._icon.stop()
            except:
                pass
            self._icon = None
        self._running = False

