"""SnapPaddleOCR - 屏幕底部提示浮窗（Toast）

半透明提示浮窗，自动关闭、点击关闭。
同一时刻只保留一个 Toast：新 Toast 出现前先销毁旧的，
防止快速连续识别时浮窗叠加堆积。
从 main_window.py 拆分而来，专职"轻提示"单一职责。
"""

import tkinter as tk
from typing import List, Optional

from . import theme
from ..utils import iter_nonempty_lines


class Toast:
    """屏幕下方半透明提示浮窗（每个 Tk root 同时仅一个实例）"""

    _current: Optional["Toast"] = None

    def __init__(self, root: tk.Misc, font_family: str) -> None:
        self._root = root
        self._font_family = font_family
        self._toast: Optional[tk.Toplevel] = None

    def show(self, text: str, duration: int = 4000) -> None:
        """显示 Toast（线程安全，实际创建被调度到主线程）

        Args:
            text: 显示的文本内容（多行自动截断为最多 3 行）
            duration: 自动关闭毫秒数，0 表示不自动关闭
        """
        if not self._root or not text:
            return
        self._root.after(0, lambda: self._show_ui(text, duration))

    def _build_display_text(self, text: str) -> Optional[str]:
        lines: List[str] = list(iter_nonempty_lines(text, limit=3))
        if not lines:
            return None
        display = "  |  ".join(lines)
        total = sum(1 for _ in iter_nonempty_lines(text))
        if total > 3:
            display += f"  ...  (+{total - 3}行)"
        max_chars = 80
        if len(display) > max_chars:
            display = display[:max_chars - 3] + "..."
        return display

    def _dismiss(self, e: Optional[tk.Event] = None) -> None:
        if self._toast is not None:
            try:
                self._toast.destroy()
            except Exception:
                pass
            self._toast = None

    def _show_ui(self, text: str, duration: int) -> None:
        display = self._build_display_text(text)
        if not display:
            return

        # 防重入：先销毁上一个 Toast，避免连续识别时浮窗堆积
        self._dismiss()

        toast = tk.Toplevel(self._root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=theme.TOAST_BG)

        lbl = tk.Label(
            toast, text=display,
            font=(self._font_family, 11),
            fg=theme.TOAST_FG, bg=theme.TOAST_BG,
            wraplength=600,
            justify=tk.LEFT,
            padx=18, pady=10,
        )
        lbl.pack()

        toast.update_idletasks()

        # 定位到屏幕底部居中
        w = toast.winfo_width()
        h = toast.winfo_height()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        toast.geometry(f"+{(sw - w) // 2}+{sh - h - 60}")

        # 半透明
        try:
            toast.attributes("-alpha", 0.92)
        except Exception:
            pass

        lbl.bind("<Button-1>", self._dismiss)
        toast.bind("<Button-1>", self._dismiss)

        self._toast = toast

        if duration > 0:
            toast.after(duration, self._dismiss)
