import ctypes
import logging
import os
import sys
import threading
import time
from typing import Any, Callable, List, Optional

from . import __version__
from .code_scanner import CodeScanner, DetectedCode
from .config import config
from .env_config import setup_paddle_env, setup_dpi_awareness, ensure_sys_path
from .hotkey import hotkey_manager
from .ocr_engine import OCREngine
from .screenshot import capture_screenshot_region
from .utils import format_hotkey_for_display

# 在导入任何模块前设置环境变量和 DPI 感知
setup_paddle_env()
setup_dpi_awareness()
ensure_sys_path()

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


class PaddleOCRTool:
    """截图 OCR 应用主控类：编排 OCR 引擎、热键、托盘与主窗口

    tkinter 必须在主线程运行；OCR 与热键注册在后台线程完成。
    """

    # OCR 触发防抖间隔（秒）：防止快速连续触发（如连按快捷键）导致多次 OCR 叠加
    OCR_DEBOUNCE_SEC = 0.8

    # 影响推理器构建的配置项：变化后需重建 OCR 引擎才能生效
    OCR_ENGINE_PARAM_KEYS = (
        "language", "ocr_version", "device", "enable_mkldnn", "cpu_threads",
        "use_doc_orientation", "use_textline_orientation",
        "text_det_limit_side_len", "text_det_limit_type",
        "text_det_thresh", "text_det_box_thresh", "text_det_unclip_ratio",
        "text_rec_score_thresh",
    )

    def __init__(self) -> None:
        self._ocr = OCREngine()
        self._code_scanner = CodeScanner()
        self._main_window: Optional[Any] = None
        self._tray: Optional[Any] = None
        self._running = True
        self._ocr_lock = threading.Lock()
        self._ocr_ready = threading.Event()
        self._last_ocr_time = 0.0
        # 当前引擎实际使用的推理参数（用于判断设置变更后是否需要重载）
        self._engine_params: dict = {}

    # ── 生命周期 ──

    def run(self) -> None:
        """启动应用（主线程），进入 tkinter 主循环直至退出"""
        self._init_ui()

    def _on_ui_ready(self) -> None:
        """UI 就绪回调（UI 主线程）：启动各后台组件初始化"""
        threading.Thread(target=self._init_ocr_bg, daemon=True).start()
        threading.Thread(target=self._init_hotkeys_bg, daemon=True).start()
        threading.Thread(target=self._init_tray_bg, daemon=True).start()

    def _init_ocr_bg(self) -> None:
        """后台初始化 OCR 引擎"""
        logger.info("正在初始化OCR引擎...")
        success = self._ocr.initialize(**config.get_all())
        if success:
            self._engine_params = self._current_engine_params()
            logger.info("OCR引擎初始化成功")
            self._update_status("OCR引擎就绪")
        else:
            err = self._ocr.error_message or "未知错误"
            logger.warning(f"OCR引擎初始化失败: {err}")
            self._update_status(f"OCR引擎初始化失败: {err}")
        self._ocr_ready.set()

    def _current_engine_params(self) -> dict:
        """读取当前配置中影响推理器的参数快照"""
        return {k: config.get(k) for k in self.OCR_ENGINE_PARAM_KEYS}

    def _on_settings_saved(self) -> None:
        """设置保存回调：刷新热键，必要时重建 OCR 引擎使推理参数立即生效"""
        self._refresh_hotkeys()
        new_params = self._current_engine_params()
        if new_params == self._engine_params:
            return
        changed = {
            k: (self._engine_params.get(k), v)
            for k, v in new_params.items()
            if self._engine_params.get(k) != v
        }
        logger.info("推理参数已变更，准备重建 OCR 引擎: %s", changed)
        threading.Thread(
            target=self._reload_engine_bg, args=(new_params,), daemon=True
        ).start()

    def _reload_engine_bg(self, new_params: dict) -> None:
        """后台重建 OCR 引擎（线程数 / 语言 / 阈值等修改后无需重启程序）"""
        with self._ocr_lock:
            self._update_status("正在应用新的推理设置...")
            if self._ocr.reload(**config.get_all()):
                self._engine_params = new_params
                logger.info("推理设置已生效")
                self._update_status("推理设置已生效")
            else:
                err = self._ocr.error_message or "未知错误"
                logger.warning("重建OCR引擎失败: %s", err)
                self._update_status(f"推理设置应用失败: {err}")

    def _init_hotkeys_bg(self) -> None:
        """后台注册全局热键，并启动锁屏监控"""
        self._ocr_ready.wait(timeout=30)
        if hotkey_manager.init():
            self._register_hotkeys()
            logger.info("全局热键已注册")
        # 启动系统锁屏/解锁监控，自动恢复失效的全局热键
        self._start_session_monitor()

    def _hotkey_bindings(self) -> dict:
        """当前配置对应的热键 → 回调映射（注册与刷新共用，避免重复）"""
        return {
            config.get("screenshot_hotkey"): self._do_screenshot_ocr_threadsafe,
            config.get("clipboard_hotkey"): self._do_clipboard_ocr_threadsafe,
            config.get("quick_ocr_hotkey"): self._do_quick_ocr_threadsafe,
        }

    def _register_hotkeys(self) -> None:
        hotkey_manager.register_all(self._hotkey_bindings())

    def _start_session_monitor(self) -> None:
        """启动系统会话锁屏/解锁监控线程

        系统锁屏或休眠后 Windows 会撤销 keyboard 库注册的低级键盘钩子，
        解锁后钩子不会自动恢复导致快捷键失效。
        此线程周期性检测锁屏状态，在解锁后自动重连热键；
        同时每 5 分钟做一次钩子存活检测，处理 Windows 静默移除钩子的情况
        （如显示模式切换、UAC 弹窗等）。
        """
        def _monitor_loop() -> None:
            was_locked = False
            last_health_check = time.time()
            health_check_interval = 300  # 5 分钟健康检查间隔

            while self._running:
                try:
                    is_locked = self._is_session_locked()

                    # 检测到从锁定→解锁的转换
                    if not is_locked and was_locked:
                        logger.info("检测到系统解锁，正在恢复全局热键...")
                        time.sleep(1.5)  # 等待系统完全恢复
                        hotkey_manager.reconnect()

                    was_locked = is_locked

                    # 周期性健康检查：Windows 可能在锁屏之外的其他场景
                    # 静默移除低级键盘钩子（显示模式切换/UAC/全屏应用等）
                    now = time.time()
                    if not is_locked and (now - last_health_check >= health_check_interval):
                        last_health_check = now
                        if hotkey_manager.has_callbacks and not hotkey_manager.is_alive():
                            logger.warning("检测到键盘钩子已失效，正在自动恢复...")
                            hotkey_manager.reconnect()

                except Exception:
                    pass
                time.sleep(3)  # 每 3 秒检测一次

        threading.Thread(target=_monitor_loop, daemon=True,
                         name="session-monitor").start()
        logger.info("会话锁屏监控已启动")

    @staticmethod
    def _is_session_locked() -> bool:
        """检测当前会话是否处于锁屏状态（OpenInputDesktop 锁屏时返回 NULL）"""
        import ctypes
        hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0)
        if hdesk != 0:
            ctypes.windll.user32.CloseDesktop(hdesk)
            return False
        return True

    def _refresh_hotkeys(self) -> None:
        """设置变更后重新注册全局热键 + 刷新 UI 按钮文字"""
        try:
            hotkey_manager.unregister_all()
            self._register_hotkeys()
            logger.info("全局热键已更新")
        except Exception as e:
            logger.warning(f"热键更新失败: {e}")
        # 同步更新主窗口工具栏按钮显示
        if self._main_window:
            self._main_window.update_hotkey_display()

    def _init_tray_bg(self) -> None:
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

    def _init_ui(self) -> None:
        """初始化 UI 并进入主循环（主线程）"""
        from .ui.main_window import MainWindow

        self._main_window = MainWindow()
        self._main_window.set_callbacks(
            on_screenshot=self._do_screenshot_ocr_threadsafe,
            on_clipboard=self._do_clipboard_ocr_threadsafe,
            screenshot_hotkey_str=format_hotkey_for_display(
                config.get("screenshot_hotkey")),
            clipboard_hotkey_str=format_hotkey_for_display(
                config.get("clipboard_hotkey")),
            on_save_settings=self._on_settings_saved,
        )

        self._main_window.set_title(f"SnapPaddleOCR v{__version__}")

        start_minimized = config.get("start_minimized", False)
        if start_minimized:
            logger.info("SnapPaddleOCR v%s 截图识别工具已启动（后台模式）", __version__)
        else:
            logger.info("SnapPaddleOCR v%s 截图识别工具已启动", __version__)
        self._on_ui_ready()
        self._main_window.show(on_close=self._on_window_close,
                               start_minimized=start_minimized)

    # ── 线程调度 ──

    def _run_in_main(self, func: Callable, *args: Any, **kwargs: Any) -> None:
        """在 UI 主线程中执行"""
        if self._main_window:
            self._main_window.schedule(func, *args, **kwargs)

    def _spawn_ocr_task(self, task: Callable[[], None]) -> None:
        """防抖检查通过后，在一次性后台线程中执行 OCR 任务"""
        if not self._debounce_ocr():
            return
        threading.Thread(target=task, daemon=True).start()

    def _debounce_ocr(self) -> bool:
        """热键防抖：短时间内重复触发则忽略"""
        now = time.time()
        if now - self._last_ocr_time < self.OCR_DEBOUNCE_SEC:
            return False
        self._last_ocr_time = now
        return True

    # 线程安全入口：热键 / 托盘 / 按钮统一经由这里调度
    def _do_screenshot_ocr_threadsafe(self) -> None:
        self._spawn_ocr_task(self._do_screenshot_ocr)

    def _do_clipboard_ocr_threadsafe(self) -> None:
        self._spawn_ocr_task(self._do_clipboard_ocr)

    def _do_quick_ocr_threadsafe(self) -> None:
        self._spawn_ocr_task(self._do_quick_ocr)

    def _toggle_window_threadsafe(self) -> None:
        """托盘图标点击：窗口可见时隐藏，隐藏时显示"""
        if self._main_window and self._main_window.is_visible:
            self._run_in_main(self._main_window.hide)
        else:
            self._run_in_main(self._show_window)

    def _show_window_threadsafe(self) -> None:
        self._toggle_window_threadsafe()

    # ── OCR 操作 ──

    def _do_screenshot_ocr(self) -> None:
        with self._ocr_lock:
            self._update_status("正在截图...")
            try:
                img = capture_screenshot_region(main_window=self._main_window)
                if img is None:
                    self._update_status("已取消截图")
                    return
                # 优先扫码：命中二维码/条形码则直接解析并复制，不再做文字识别
                if self._try_scan_codes(img):
                    return
                self._update_status("正在识别...")
                result = self._ocr.recognize(img)
                self._handle_result(result)
            except Exception as e:
                logger.exception("截图OCR失败")
                self._update_status(f"截图OCR失败: {e}")

    def _do_clipboard_ocr(self) -> None:
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
                logger.exception("剪贴板OCR失败")
                self._update_status(f"剪贴板OCR失败: {e}")

    def _do_quick_ocr(self) -> None:
        """快速 OCR：不弹结果窗，直接复制 + Toast 轻提示"""
        with self._ocr_lock:
            try:
                img = capture_screenshot_region(main_window=self._main_window)
                if img is None:
                    return
                # 优先扫码：命中二维码/条形码则直接解析并复制
                if self._try_scan_codes(img):
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
                logger.exception("快速OCR失败")

    # ── 扫码 ──

    def _try_scan_codes(self, image: Any) -> bool:
        """尝试解析图片中的二维码/条形码

        Args:
            image: 截图得到的 PIL.Image

        Returns:
            True 表示已成功解析并处理（调用方应跳过文字识别），
            False 表示未发现条码，继续走 OCR 流程
        """
        if not config.get("scan_codes", True):
            return False

        codes = self._code_scanner.scan(image)
        if not codes:
            return False

        self._handle_codes(codes)
        return True

    def _handle_codes(self, codes: List[DetectedCode]) -> None:
        """处理扫码结果：复制到剪贴板 + Toast 提示 + 记录到结果列表"""
        text = "\n".join(c.text for c in codes)
        # 码制名称去重，如 "QRCode"、"QRCode、Code128"
        formats = "、".join(dict.fromkeys(c.format for c in codes))

        self._copy_to_clipboard(text)
        self._update_status(f"已识别 {formats}，内容已复制到剪贴板")
        self._notify("扫码完成", f"已解析 {formats}")
        if self._main_window and config.get("show_toast", True):
            self._main_window.show_toast(text, duration=2500)
        if self._main_window:
            label = "扫码"
            self._run_in_main(
                lambda t=text, f=formats: self._main_window.add_result(
                    t, time.strftime('%H:%M:%S'), tag=f"{label}·{f}"
                )
            )

    def _handle_result(self, result: dict) -> None:
        """处理 OCR 结果：展示 / 复制 / 通知"""
        if result["code"] != 100:
            self._update_status(f"识别失败: {result['data']}")
            return

        items = [d for d in result["data"] if d.get("text", "").strip()]
        if not items:
            self._update_status("未识别到文字")
            self._notify("OCR结果", "未识别到文字")
            return

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

    @staticmethod
    def _apply_layout(items: list) -> str:
        """按排版规则格式化识别结果"""
        layout = config.get("result_layout", "raw")
        texts = [d["text"].strip() for d in items if d.get("text", "").strip()]
        if not texts:
            return ""
        if layout == "none":
            return "  ".join(texts)
        return "\n".join(texts)

    def _show_result(self, text: str, popup: bool = True) -> None:
        if self._main_window:
            if popup and not self._main_window.is_visible:
                self._main_window.show_window()
            self._main_window.add_result(text, time.strftime('%H:%M:%S'))

    def _update_status(self, text: str) -> None:
        if self._main_window:
            self._main_window.set_status(text)
        logger.info(text)

    def _copy_to_clipboard(self, text: str) -> None:
        """将文本复制到系统剪贴板（调度到主线程执行）"""
        def _do_copy() -> None:
            from .ui.theme import copy_to_clipboard
            if self._main_window and self._main_window.root:
                if not copy_to_clipboard(self._main_window.root, text):
                    logger.warning("复制到剪贴板失败")

        self._run_in_main(_do_copy)

    def _notify(self, title: str, message: str) -> None:
        if self._tray:
            self._tray.notify(title, message)

    # ── 退出 ──

    def _on_window_close(self) -> None:
        """主窗口关闭按钮 X 的处理（根据 close_action 配置决定行为）"""
        if config.get("close_action", "minimize") == "minimize":
            if self._main_window:
                self._main_window.hide()
        else:
            self._quit()

    def _show_window(self) -> None:
        if self._main_window:
            self._main_window.show_window()

    def _quit(self) -> None:
        """按依赖顺序释放资源并退出"""
        logger.info("正在退出...")
        self._running = False
        try:
            hotkey_manager.close()
        except Exception:
            pass
        if self._tray:
            self._tray.stop()
        if self._ocr:
            self._ocr.close()
        if self._main_window:
            self._main_window.close()


def main() -> None:
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
