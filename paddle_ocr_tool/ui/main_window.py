"""SnapPaddleOCR - 主窗口（Modern UI）

仅负责窗口框架搭建与组件编排；选区覆盖层、结果卡片、
Toast 等具体职责分别由 selection_overlay / result_panel / toast 承担。
"""

import os
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

from . import theme
from .result_panel import ResultPanel
from .selection_overlay import SelectionOverlay
from .toast import Toast
from ..config import config
from ..utils import format_hotkey_for_display


class MainWindow:
    """主界面窗口"""

    def __init__(self) -> None:
        self._root: Optional[tk.Tk] = None
        self._status_label: Optional[tk.Label] = None
        self._on_close_callback: Optional[Callable[[], None]] = None
        self._on_screenshot_cb: Optional[Callable[[], None]] = None
        self._on_clipboard_cb: Optional[Callable[[], None]] = None
        self._on_save_settings_cb: Optional[Callable[[], None]] = None
        self._btn_scr: Optional[ttk.Button] = None
        self._btn_clp: Optional[ttk.Button] = None
        self._font_family = "TkDefaultFont"
        self._title = "SnapPaddleOCR · 截图速识"
        self._screenshot_hotkey_str = "Ctrl+Shift+F"
        self._clipboard_hotkey_str = "Ctrl+Shift+G"
        self._result_panel: Optional[ResultPanel] = None
        self._toast: Optional[Toast] = None
        self._card_canvas: Optional[tk.Canvas] = None

    # ── 配置与回调 ──

    def set_title(self, title: str) -> None:
        """设置窗口标题（在 show() 之前调用）"""
        self._title = title

    def set_callbacks(self, on_screenshot: Optional[Callable[[], None]] = None,
                      on_clipboard: Optional[Callable[[], None]] = None,
                      screenshot_hotkey_str: Optional[str] = None,
                      clipboard_hotkey_str: Optional[str] = None,
                      on_save_settings: Optional[Callable[[], None]] = None) -> None:
        self._on_screenshot_cb = on_screenshot
        self._on_clipboard_cb = on_clipboard
        self._screenshot_hotkey_str = screenshot_hotkey_str or self._screenshot_hotkey_str
        self._clipboard_hotkey_str = clipboard_hotkey_str or self._clipboard_hotkey_str
        self._on_save_settings_cb = on_save_settings

    def schedule(self, func: Callable, *args: Any, **kwargs: Any) -> None:
        """线程安全接口：将调用调度到 Tk 主线程执行"""
        if self._root:
            self._root.after(0, func, *args, **kwargs)

    @property
    def root(self) -> Optional[tk.Tk]:
        """Tk 根窗口（供主控类调度主线程任务）"""
        return self._root

    # ── 窗口构建 ──

    def show(self, on_close: Optional[Callable[[], None]] = None,
             start_minimized: bool = False) -> None:
        self._on_close_callback = on_close

        self._root = tk.Tk()
        self._root.title(self._title)
        # 程序图标
        from ..paths import resource_path
        ico_path = resource_path("paddle_ocr_tool/ui/main.ico")
        if os.path.exists(ico_path):
            self._root.iconbitmap(ico_path)
        # 按屏幕物理像素等比缩放窗口（PMv2 下 winfo 返回物理像素）
        self._root.update_idletasks()
        sw, sh = self._root.winfo_screenwidth(), self._root.winfo_screenheight()
        ww, wh = max(860, int(sw * 0.42)), max(620, int(sh * 0.55))
        mw, mh = max(680, int(sw * 0.32)), max(420, int(sh * 0.38))
        self._root.geometry(f"{ww}x{wh}")
        self._root.minsize(mw, mh)
        self._root.configure(bg=theme.BG)

        # ── 字体检测 ──
        if self._font_exists("Microsoft YaHei"):
            self._font_family = "Microsoft YaHei"
        elif self._font_exists("微软雅黑"):
            self._font_family = "微软雅黑"
        elif self._font_exists("SimHei"):
            self._font_family = "SimHei"
        else:
            self._font_family = "TkDefaultFont"

        theme.setup_style(self._root, self._font_family)

        self._build_header()
        self._build_toolbar()
        self._build_content()
        self._build_statusbar()

        # ── 事件 ──
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.bind("<Control-f>", lambda e: self._on_screenshot())
        self._root.bind("<Control-g>", lambda e: self._on_clipboard())

        # 启动时隐藏主窗口
        if start_minimized:
            self._root.withdraw()

        self._root.mainloop()

    def _build_header(self) -> None:
        header = tk.Frame(self._root, bg=theme.PRIMARY, height=48)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="SnapPaddleOCR",
                 font=(self._font_family, 14, "bold"),
                 fg="white", bg=theme.PRIMARY).pack(side=tk.LEFT, padx=16, pady=10)
        tk.Label(header, text="截图速识", font=(self._font_family, 10),
                 fg="#B3D4FC", bg=theme.PRIMARY).pack(side=tk.LEFT, pady=10)

    def _build_toolbar(self) -> None:
        tb = tk.Frame(self._root, bg=theme.SURFACE, height=44)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)

        ctn = tk.Frame(tb, bg=theme.SURFACE)
        ctn.pack(side=tk.LEFT, padx=10)

        def _mkbtn(parent: tk.Misc, text: str, cmd: Callable[[], None],
                   primary: bool = False) -> ttk.Button:
            st = "Primary.TButton" if primary else "TButton"
            btn = ttk.Button(parent, text=text, command=cmd, style=st)
            btn.pack(side=tk.LEFT, padx=(0, 6), pady=5)
            return btn

        self._btn_scr = _mkbtn(ctn, self._screenshot_btn_text(),
                               self._on_screenshot, primary=True)
        self._btn_clp = _mkbtn(ctn, self._clipboard_btn_text(),
                               self._on_clipboard, primary=True)
        _mkbtn(ctn, "  🗑  清空  ", self._on_clear)
        _mkbtn(ctn, "  📄  复制结果  ", self._on_copy)

        r_ctn = tk.Frame(tb, bg=theme.SURFACE)
        r_ctn.pack(side=tk.RIGHT, padx=10)
        ttk.Button(r_ctn, text="  ⚙  设置  ", command=self._on_settings,
                   style="Secondary.TButton").pack(side=tk.RIGHT, padx=(4, 0), pady=5)

    def _build_content(self) -> None:
        assert self._root is not None
        cf = tk.Frame(self._root, bg=theme.SURFACE)
        cf.pack(fill=tk.BOTH, expand=True)

        self._card_canvas = tk.Canvas(cf, bg=theme.SURFACE, highlightthickness=0)
        scrollbar = ttk.Scrollbar(cf, orient=tk.VERTICAL,
                                  command=self._card_canvas.yview)

        self._result_panel = ResultPanel(
            self._root, cf, self._card_canvas, self._font_family,
            on_status=self.set_status)
        self._card_canvas.configure(yscrollcommand=scrollbar.set)
        self._card_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 鼠标滚轮滚动（canvas + 内部 frame 均绑定，覆盖卡片区域）
        on_wheel = theme.make_wheel_scroller(self._card_canvas)
        self._card_canvas.bind("<MouseWheel>", on_wheel)
        self._result_panel.frame.bind("<MouseWheel>", on_wheel)
        self._card_canvas.bind("<Enter>", lambda e: self._card_canvas.focus_set())
        self._card_canvas.bind("<Leave>", lambda e: self._root.focus_set())

        self._toast = Toast(self._root, self._font_family)

    def _build_statusbar(self) -> None:
        self._status_label = tk.Label(
            self._root,
            text="正在初始化...",
            anchor=tk.W,
            padx=14, pady=5,
            font=(self._font_family, 9),
            fg=theme.TEXT_SECONDARY, bg=theme.BORDER,
            relief="flat")
        self._status_label.pack(fill=tk.X)

    def _font_exists(self, family: str) -> bool:
        try:
            from tkinter import font
            return family.lower() in [f.lower() for f in font.families()]
        except Exception:
            return True

    # ── 截图区域选择（委托给 SelectionOverlay） ──

    def start_region_selection(self) -> Optional[Any]:
        """启动区域选择：冻结画面后等待用户框选，返回裁剪的 PIL.Image 或 None"""
        if not self._root:
            return None
        return SelectionOverlay(self._root, self._font_family).select()

    # ── 热键显示 ──

    def _screenshot_btn_text(self) -> str:
        return f"  📷  截图OCR  ({self._screenshot_hotkey_str})  "

    def _clipboard_btn_text(self) -> str:
        return f"  📋  剪贴板OCR  ({self._clipboard_hotkey_str})  "

    def update_hotkey_display(self) -> None:
        """设置变更后刷新工具栏快捷键按钮文字（线程安全）"""
        self._screenshot_hotkey_str = format_hotkey_for_display(
            config.get("screenshot_hotkey", "ctrl+shift+f"))
        self._clipboard_hotkey_str = format_hotkey_for_display(
            config.get("clipboard_hotkey", "ctrl+shift+g"))

        if self._root and self._btn_scr:
            self._root.after(0, lambda: (
                self._btn_scr.config(text=self._screenshot_btn_text()),
                self._btn_clp.config(text=self._clipboard_btn_text())
            ))

    # ── 界面操作 ──

    def _on_screenshot(self) -> None:
        if self._on_screenshot_cb and self._root:
            self.hide()                       # 隐藏主窗口，避免出现在截图中
            self._root.update_idletasks()     # 立即刷新
            self._root.after(500, self._on_screenshot_cb)  # 延迟 0.5s 等窗口完全消失

    def _on_clipboard(self) -> None:
        if self._on_clipboard_cb:
            self._on_clipboard_cb()

    def _on_clear(self) -> None:
        if self._result_panel:
            self._result_panel.clear()

    def _on_copy(self) -> None:
        if not (self._result_panel and self._root):
            return
        all_text = self._result_panel.get_all_text()
        if all_text and theme.copy_to_clipboard(self._root, all_text):
            self.set_status("已复制全部到剪贴板")

    def _on_settings(self) -> None:
        from .settings_window import SettingsWindow
        SettingsWindow(self._root, font_family=self._font_family,
                       on_save_hotkey=self._on_save_settings_cb)

    def _on_close(self) -> None:
        if self._on_close_callback:
            self._on_close_callback()
        elif self._root:
            self._root.destroy()

    # ── 对外公开接口（线程安全） ──

    def add_result(self, text: str, timestamp: Optional[str] = None) -> None:
        """添加一条识别记录卡片（自动滚动到底部，超过上限时移除最旧记录）"""
        if not self._result_panel:
            return
        self._root.after(0, lambda: self._result_panel.add(text, timestamp))

    def show_toast(self, text: str, duration: int = 4000) -> None:
        """屏幕下方半透明提示浮窗"""
        if self._toast:
            self._toast.show(text, duration)

    def set_status(self, text: str) -> None:
        if self._status_label and self._root:
            self._root.after(0, lambda: self._status_label.config(text=str(text)))

    def hide(self) -> None:
        if self._root:
            self._root.withdraw()

    def show_window(self) -> None:
        if self._root:
            self._root.after(0, lambda: (
                self._root.deiconify(),
                self._root.lift(),
                self._root.focus_force()))

    @property
    def is_visible(self) -> bool:
        return bool(self._root and self._root.winfo_exists()
                    and self._root.state() != "withdrawn")

    def close(self) -> None:
        if self._root:
            try:
                self._root.quit()
                self._root.destroy()
            except Exception:
                pass
            self._root = None
            self._result_panel = None
            self._toast = None
