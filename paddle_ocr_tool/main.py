import logging
import ctypes
import os
import threading
import time
import sys

# 在导入任何模块前设置环境变量和 DPI 感知
from .env_config import setup_paddle_env, setup_dpi_awareness, ensure_sys_path

setup_paddle_env()
setup_dpi_awareness()
ensure_sys_path()

from . import __version__
from .config import config
from .ocr_engine import OCREngine
from .screenshot import capture_screenshot_region, ScreenCapture
from .hotkey import hotkey_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("SnapPaddleOCR")

# ── 单实例互斥锁 ──
_MUTEX_NAME = "Global\\SnapPaddleOCR_SingleInstance_Mutex"


def _check_single_instance() -> bool:
    """检查是否已有实例在运行，返回 True 表示可以继续运行"""
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            return True
        last_error = kernel32.GetLastError()
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        # 保存句柄防止被 GC 回收（程序退出时自动释放）
        import atexit
        atexit.register(lambda h=handle: kernel32.CloseHandle(h))
        return True
    except Exception:
        return True


def _format_hotkey_for_display(hotkey):
    """将 'ctrl+shift+f' 格式转为 'Ctrl+Shift+F' 显示格式"""
    return "+".join(w.capitalize() for w in hotkey.split("+"))


class PaddleOCRTool:
    """截图OCR应用主类 - tkinter必须在主线程运行"""
    
    def __init__(self):
        self._ocr = OCREngine()
        self._main_window = None
        self._tray = None
        self._running = False
        self._ocr_lock = threading.Lock()
        self._ocr_ready = threading.Event()
    
    def run(self):
        """启动应用 - 主线程运行"""
        self._running = True
        self._init_ui()
    
    def _on_ui_ready(self):
        """UI就绪回调 - 在UI主线程中调用"""
        # 后台初始化OCR
        threading.Thread(target=self._init_ocr_bg, daemon=True).start()
        # 后台初始化热键
        threading.Thread(target=self._init_hotkeys_bg, daemon=True).start()
        # 后台初始化托盘
        threading.Thread(target=self._init_tray_bg, daemon=True).start()
    
    def _init_ocr_bg(self):
        """后台初始化OCR引擎"""
        logger.info("正在初始化OCR引擎...")
        params = config.get_all()
        success = self._ocr.initialize(**params)
        if success:
            logger.info("OCR引擎初始化成功")
            self._update_status("OCR引擎就绪")
        else:
            err = self._ocr.error_message or "未知错误"
            logger.warning(f"OCR引擎初始化失败: {err}")
            self._update_status(f"OCR引擎初始化失败: {err}")
        self._ocr_ready.set()
    
    def _init_hotkeys_bg(self):
        """后台注册热键"""
        self._ocr_ready.wait(timeout=30)
        if hotkey_manager.init():
            hotkey_manager.register(config.get("screenshot_hotkey"), self._do_screenshot_ocr_threadsafe)
            hotkey_manager.register(config.get("clipboard_hotkey"), self._do_clipboard_ocr_threadsafe)
            hotkey_manager.register(config.get("quick_ocr_hotkey"), self._do_quick_ocr_threadsafe)
            logger.info("全局热键已注册")
        # 启动系统锁屏/解锁监控，自动恢复失效的全局热键
        self._start_session_monitor()

    def _start_session_monitor(self):
        """启动系统会话锁屏/解锁监控线程
        
        系统锁屏或休眠后 Windows 会撤销 keyboard 库注册的低级键盘钩子，
        解锁后钩子不会自动恢复导致快捷键失效。
        此线程周期性检测锁屏状态，在解锁后自动重连热键。
        """
        import ctypes

        def _monitor_loop():
            was_locked = False
            while self._running:
                try:
                    # OpenInputDesktop 在锁屏时返回 NULL
                    hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0)
                    is_locked = (hdesk == 0)
                    if hdesk != 0:
                        ctypes.windll.user32.CloseDesktop(hdesk)

                    # 检测到从锁定→解锁的转换
                    if not is_locked and was_locked:
                        logger.info("检测到系统解锁，正在恢复全局热键...")
                        time.sleep(1.5)  # 等待系统完全恢复
                        hotkey_manager.reconnect()

                    was_locked = is_locked
                except Exception:
                    pass
                time.sleep(3)  # 每 3 秒检测一次

        threading.Thread(target=_monitor_loop, daemon=True, name="session-monitor").start()
        logger.info("会话锁屏监控已启动")

    def _refresh_hotkeys(self):
        """设置变更后重新注册全局热键 + 刷新 UI 按钮文字"""
        if not hotkey_manager._keyboard:
            return
        try:
            hotkey_manager.unregister_all()
            hotkey_manager.register(config.get("screenshot_hotkey"), self._do_screenshot_ocr_threadsafe)
            hotkey_manager.register(config.get("clipboard_hotkey"), self._do_clipboard_ocr_threadsafe)
            hotkey_manager.register(config.get("quick_ocr_hotkey"), self._do_quick_ocr_threadsafe)
            logger.info("全局热键已更新")
        except Exception as e:
            logger.warning(f"热键更新失败: {e}")
        # 同步更新主窗口工具栏按钮显示
        if self._main_window:
            self._main_window.update_hotkey_display()
    
    def _init_tray_bg(self):
        """后台初始化托盘"""
        try:
            from .ui.tray import SystemTray
            self._tray = SystemTray()
            if self._tray.init():
                self._tray.run(
                    on_show=self._show_window_threadsafe,
                    on_ocr=self._do_screenshot_ocr_threadsafe,
                    on_clipboard_ocr=self._do_clipboard_ocr_threadsafe,
                    on_quit=self._quit,
                )
        except Exception as e:
            logger.warning(f"系统托盘初始化失败: {e}")
    
    def _init_ui(self):
        """初始化UI并启动主循环（主线程）"""
        from .ui.main_window import MainWindow
        
        self._main_window = MainWindow()
        self._main_window.set_callbacks(
            on_screenshot=self._do_screenshot_ocr_threadsafe,
            on_clipboard=self._do_clipboard_ocr_threadsafe,
            screenshot_hotkey_str=_format_hotkey_for_display(config.get("screenshot_hotkey")),
            clipboard_hotkey_str=_format_hotkey_for_display(config.get("clipboard_hotkey")),
            on_save_settings=self._refresh_hotkeys,
        )
        
        # 设置窗口标题（含版本号）
        self._main_window.set_title(f"SnapPaddleOCR v{__version__}")

        # 直接在主线程中运行 show（会进入 mainloop）
        start_minimized = config.get("start_minimized", False)
        if start_minimized:
            logger.info("SnapPaddleOCR v%s 截图识别工具已启动（后台模式）", __version__)
        else:
            logger.info("SnapPaddleOCR v%s 截图识别工具已启动", __version__)
        self._on_ui_ready()
        self._main_window.show(on_close=self._on_window_close,
                               start_minimized=start_minimized)
    
    # ========== 线程安全的方法 ==========
    
    def _run_in_main(self, func, *args, **kwargs):
        """在UI主线程中执行"""
        if self._main_window and self._main_window._root:
            self._main_window._root.after(0, func, *args, **kwargs)
    
    def _do_screenshot_ocr_threadsafe(self):
        threading.Thread(target=self._do_screenshot_ocr, daemon=True).start()
    
    def _do_clipboard_ocr_threadsafe(self):
        threading.Thread(target=self._do_clipboard_ocr, daemon=True).start()
    
    def _do_quick_ocr_threadsafe(self):
        threading.Thread(target=self._do_quick_ocr, daemon=True).start()
    
    def _toggle_window_threadsafe(self):
        """托盘图标点击：窗口可见时隐藏，隐藏时显示"""
        if self._main_window and self._main_window.is_visible:
            self._run_in_main(self._main_window.hide)
        else:
            self._run_in_main(self._show_window)

    def _show_window_threadsafe(self):
        self._toggle_window_threadsafe()
    
    # ========== OCR 操作 ==========
    
    def _do_screenshot_ocr(self):
        with self._ocr_lock:
            self._update_status("正在截图...")
            try:
                img = capture_screenshot_region(main_window=self._main_window)
                if img is None:
                    self._update_status("已取消截图")
                    return
                self._update_status("正在识别...")
                result = self._ocr.recognize(img)
                self._handle_result(result)
            except Exception as e:
                logger.error(f"截图OCR失败: {e}")
                self._update_status(f"截图OCR失败: {e}")
    
    def _do_clipboard_ocr(self):
        with self._ocr_lock:
            try:
                from PIL import ImageGrab
                self._update_status("正在读取剪贴板...")
                img = ImageGrab.grabclipboard()
                if img is None:
                    self._update_status("剪贴板中没有图片")
                    return
                self._update_status("正在识别...")
                result = self._ocr.recognize(img)
                self._handle_result(result)
            except Exception as e:
                logger.error(f"剪贴板OCR失败: {e}")
                self._update_status(f"剪贴板OCR失败: {e}")
    
    def _do_quick_ocr(self):
        with self._ocr_lock:
            try:
                img = capture_screenshot_region(main_window=self._main_window)
                if img is None:
                    return
                result = self._ocr.recognize(img)
                if result["code"] == 100:
                    items = [d for d in result["data"] if d.get("text", "").strip()]
                    if items:
                        text = self._apply_layout(items)
                        self._copy_to_clipboard(text)
                        self._notify("OCR结果", f"已复制 {len(items)} 段文字")
                        if self._main_window and config.get("show_toast", True):
                            self._main_window.show_toast(text, duration=2500)
                        # 同时记录到主窗口识别列表（不弹窗）
                        self._run_in_main(
                            lambda t=text: self._main_window.add_result(
                                t, time.strftime('%H:%M:%S')
                            )
                        )
                else:
                    self._notify("OCR失败", result["data"])
            except Exception as e:
                logger.error(f"快速OCR失败: {e}")
    
    def _handle_result(self, result):
        if result["code"] == 100:
            items = [d for d in result["data"] if d.get("text", "").strip()]
            if items:
                result_text = self._apply_layout(items)
                popup = config.get("show_result_window", True)
                self._run_in_main(lambda: self._show_result(result_text, popup=popup))
                # 屏幕下方 Toast 提示（可关闭）
                if self._main_window and config.get("show_toast", True):
                    self._main_window.show_toast(result_text)
                if config.get("auto_copy"):
                    self._copy_to_clipboard(result_text)
                    self._update_status(f"识别完成，已复制到剪贴板 ({len(items)}段)")
                else:
                    self._update_status(f"识别完成 ({len(items)}段)")
                self._notify("OCR识别完成", f"识别到 {len(items)} 段文字")
            else:
                self._update_status("未识别到文字")
                self._notify("OCR结果", "未识别到文字")
        else:
            self._update_status(f"识别失败: {result['data']}")

    @staticmethod
    def _apply_layout(items):
        """按排版规则格式化识别结果"""
        layout = config.get("result_layout", "raw")
        texts = [d["text"].strip() for d in items if d.get("text", "").strip()]
        if not texts:
            return ""
        if layout == "none":
            return "  ".join(texts)
        return "\n".join(texts)

    def _show_result(self, text, popup=True):
        if self._main_window:
            if popup and not self._main_window.is_visible:
                self._main_window.show_window()
            self._main_window.add_result(text, time.strftime('%H:%M:%S'))
    
    def _update_status(self, text):
        if self._main_window:
            self._main_window.set_status(text)
        logger.info(text)
    
    def _copy_to_clipboard(self, text):
        """线程安全地复制文本到剪贴板"""
        try:
            import tkinter as tk
            # 使用已有的 root 实例，避免创建新的 Tk 实例导致资源泄漏
            if self._main_window and self._main_window._root:
                self._run_in_main(lambda: (
                    self._main_window._root.clipboard_clear(),
                    self._main_window._root.clipboard_append(text),
                    self._main_window._root.update()
                ))
            else:
                # 备用方案：创建临时 Tk 实例（仅在必要时）
                r = tk.Tk()
                r.withdraw()
                r.clipboard_clear()
                r.clipboard_append(text)
                r.update()
                r.destroy()
        except Exception as e:
            logger.warning(f"复制到剪贴板失败：{e}")

    def _notify(self, title, message):
        if self._tray:
            self._tray.notify(title, message)
    
    def _on_window_close(self):
        """主窗口关闭按钮 X 的处理（根据 close_action 配置决定行为）"""
        if config.get("close_action", "minimize") == "minimize":
            if self._main_window:
                self._main_window.hide()
        else:
            self._quit()

    def _show_window(self):
        if self._main_window:
            self._main_window.show_window()
    
    def _quit(self):
        logger.info("正在退出...")
        self._running = False
        hotkey_manager.close()
        if self._tray:
            self._tray.stop()
        if self._ocr:
            self._ocr.close()
        if self._main_window:
            self._main_window.close()
        os._exit(0)


def main():
    if not _check_single_instance():
        import tkinter.messagebox as mb
        mb.showwarning(
            "SnapPaddleOCR",
            "SnapPaddleOCR 已在运行中，请检查系统托盘。\n\n"
            "点击托盘图标即可显示主窗口。",
        )
        sys.exit(0)
    tool = PaddleOCRTool()
    tool.run()


if __name__ == "__main__":
    main()

