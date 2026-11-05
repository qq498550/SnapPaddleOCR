"""SnapPaddleOCR - UI 主题与共享 UI 工具

所有窗口/控件的配色、ttk 样式、剪贴板与滚轮滚动等
跨窗口复用的 UI 逻辑统一收敛在本模块，避免多处重复定义。
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable

# ── 配色（全应用唯一来源）──
PRIMARY = "#1565C0"
PRIMARY_LIGHT = "#1E88E5"
PRIMARY_DARK = "#0D47A1"
BG = "#F5F5F5"
SURFACE = "#FFFFFF"
TEXT = "#212121"
TEXT_SECONDARY = "#757575"
BORDER = "#E0E0E0"
HOVER = "#E3F2FD"

TOAST_BG = "#DF9C9C"
TOAST_FG = "#FFFFFF"


def setup_style(root: tk.Misc, font_family: str) -> ttk.Style:
    """配置全局 ttk 样式"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", background=BG, foreground=TEXT,
                    font=(font_family, 10))
    style.configure("TButton",
                    background=SURFACE, foreground=TEXT,
                    borderwidth=1, focusthickness=0, focuscolor="none",
                    padding=(12, 4))
    style.map("TButton",
              background=[("active", HOVER), ("pressed", BORDER)],
              relief=[("pressed", "sunken")])

    style.configure("Primary.TButton",
                    background=PRIMARY, foreground="white",
                    borderwidth=0, focuscolor="none",
                    padding=(14, 6))
    style.map("Primary.TButton",
              background=[("active", PRIMARY_LIGHT), ("pressed", PRIMARY_DARK)],
              foreground=[("active", "white"), ("pressed", "white")])

    style.configure("Secondary.TButton",
                    background=SURFACE, foreground=TEXT_SECONDARY,
                    borderwidth=1, focusthickness=0, focuscolor="none",
                    padding=(10, 3))
    style.map("Secondary.TButton",
              background=[("active", HOVER)],
              foreground=[("active", PRIMARY)])

    style.configure("Sub.TLabel", font=(font_family, 9),
                    background=BG, foreground=TEXT_SECONDARY)
    style.configure("TSeparator", background=BORDER)
    style.configure("Status.TLabel", font=(font_family, 9),
                    background=BORDER, foreground=TEXT_SECONDARY,
                    relief="solid", borderwidth=1, padding=(8, 5))
    style.configure("TEntry", font=(font_family, 10),
                    fieldbackground=SURFACE, foreground=TEXT,
                    borderwidth=1, padding=(6, 3))
    return style


def copy_to_clipboard(widget: tk.Misc, text: str) -> bool:
    """将文本写入系统剪贴板（必须在 Tk 主线程中调用）

    Args:
        widget: 任意 Tk 控件（借其所属解释器访问剪贴板）
        text: 要复制的文本

    Returns:
        是否复制成功
    """
    try:
        widget.clipboard_clear()
        widget.clipboard_append(text)
        # 多次刷新消息队列，确保剪贴板写入在窗口销毁前完成
        widget.update_idletasks()
        widget.update()
        return True
    except Exception:
        return False


def make_wheel_scroller(canvas: tk.Canvas) -> Callable[[tk.Event], None]:
    """创建绑定到指定 Canvas 的鼠标滚轮滚动回调

    Args:
        canvas: 要滚动的 Canvas

    Returns:
        可直接绑定到 <MouseWheel> 的回调函数
    """
    def _on_wheel(event: tk.Event) -> None:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    return _on_wheel
