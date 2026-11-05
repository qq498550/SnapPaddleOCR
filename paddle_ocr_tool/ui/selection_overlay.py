"""SnapPaddleOCR - 全屏冻结选区覆盖层

将触发瞬间的全屏画面冻结为静态背景并叠加暗色遮罩，
用户在静止画面上框选识别区域，完成后返回裁剪出的 PIL Image。
从 main_window.py 拆分而来，专职"截图选区"单一职责。
"""

import ctypes
import threading
import tkinter as tk
from typing import Optional

from PIL import Image


def capture_fullscreen_virtual() -> Optional[Image.Image]:
    """抓取全屏并缩放到虚拟桌面尺寸，确保与 tkinter 坐标系对齐

    PIL.ImageGrab.grab() 内部会临时切换 DPI 感知，返回物理像素图
    （如 3840×2160）。通过 GetSystemMetrics 获取虚拟桌面尺寸
    （如 1707×960），将物理图 resize 到虚拟尺寸后，坐标与 tkinter
    overlay 完全一致。

    Returns:
        虚拟坐标尺寸的 PIL.Image，失败返回 None
    """
    user32 = ctypes.windll.user32

    # 虚拟桌面尺寸（DPI 无感知返回虚拟坐标）
    vs_w = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    vs_h = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN

    if vs_w <= 0 or vs_h <= 0:
        return None

    try:
        from PIL import ImageGrab
        full_img = ImageGrab.grab(all_screens=True)
        if full_img.size != (vs_w, vs_h):
            full_img = full_img.resize((vs_w, vs_h), Image.LANCZOS)
    except Exception:
        return None

    return full_img


class SelectionOverlay:
    """全屏画面冻结区域选择器"""

    def __init__(self, root: tk.Misc, font_family: str) -> None:
        self._root = root
        self._font_family = font_family
        self._result: Optional[Image.Image] = None
        self._done = threading.Event()

    def select(self, timeout: float = 120) -> Optional[Image.Image]:
        """冻结画面并等待用户框选

        Args:
            timeout: 等待用户完成选区的最长秒数

        Returns:
            裁剪出的 PIL.Image；取消或失败返回 None
        """
        full_img = capture_fullscreen_virtual()
        if full_img is None:
            return None

        self._done.clear()
        # overlay 必须在 Tk 主线程创建
        self._root.after(0, lambda: self._create_overlay(full_img))
        self._done.wait(timeout=timeout)
        return self._result

    # ── overlay 创建与交互（均在 Tk 主线程） ──

    def _create_overlay(self, full_img: Image.Image) -> None:
        from PIL import ImageTk

        prev_grabbed = None
        try:
            prev_grabbed = self._root.grab_current()
            if prev_grabbed and prev_grabbed != self._root:
                prev_grabbed.grab_release()
        except Exception:
            pass

        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()

        # ── 冻结层：全屏窗口，背景为触发瞬间的静态画面 ──
        freeze_overlay = tk.Toplevel(self._root)
        freeze_overlay.attributes("-fullscreen", True)
        freeze_overlay.attributes("-topmost", True)
        freeze_overlay.configure(cursor="crosshair", bg="black")
        freeze_overlay.grab_set()

        canvas = tk.Canvas(
            freeze_overlay, width=sw, height=sh,
            highlightthickness=0, cursor="crosshair",
        )
        canvas.pack()

        # 将冻结画面绘制为 canvas 背景
        tk_img = ImageTk.PhotoImage(full_img)
        freeze_overlay._frozen_ref = tk_img  # 防止 GC
        canvas.create_image(0, 0, image=tk_img, anchor=tk.NW)

        # ── 操作提示 ──
        canvas.create_text(
            sw // 2, 30,
            text="按住左键拖选识别区域 ｜ 右键/ESC 取消",
            fill="#FFFFFF", font=(self._font_family, 16),
        )

        sel = {"sx": None, "sy": None, "rect": None}

        # ── 十字坐标线 ──
        cross_v = canvas.create_line(0, 0, 0, 0, fill="#00FF00", width=1, tags="cross")
        cross_h = canvas.create_line(0, 0, 0, 0, fill="#00FF00", width=1, tags="cross")

        def _update_crosshair(x: float, y: float) -> None:
            canvas.coords(cross_v, x, 0, x, sh)
            canvas.coords(cross_h, 0, y, sw, y)

        def _show_crosshair() -> None:
            for item in canvas.find_withtag("cross"):
                canvas.itemconfigure(item, state="normal")

        def _hide_crosshair() -> None:
            for item in canvas.find_withtag("cross"):
                canvas.itemconfigure(item, state="hidden")

        # 初始隐藏，鼠标进入 overlay 后才显示
        _hide_crosshair()

        def _cleanup() -> None:
            try:
                freeze_overlay.grab_release()
                freeze_overlay.destroy()
            except Exception:
                pass
            if prev_grabbed and prev_grabbed.winfo_exists():
                try:
                    prev_grabbed.grab_set()
                except Exception:
                    pass

        def _crop(sx: float, sy: float, ex: float, ey: float) -> None:
            """在冻结画面上精准裁切"""
            l, t = min(sx, ex), min(sy, ey)
            r, b = max(sx, ex), max(sy, ey)
            if r - l < 5 or b - t < 5:
                self._result = None
                return
            try:
                self._result = full_img.crop((int(l), int(t), int(r), int(b)))
            except Exception:
                self._result = None

        def on_down(e: tk.Event) -> None:
            sel["sx"], sel["sy"] = e.x, e.y
            _hide_crosshair()  # 拖选时隐藏十字线
            # 选中区域高亮（橙框描边）
            sel["rect"] = canvas.create_rectangle(
                e.x, e.y, e.x, e.y,
                outline="#FF5722", width=3,
            )

        def on_move(e: tk.Event) -> None:
            if sel["rect"] and sel["sx"] is not None:
                canvas.coords(sel["rect"], sel["sx"], sel["sy"], e.x, e.y)

        def on_motion(e: tk.Event) -> None:
            """鼠标移动时更新十字坐标线（仅在非拖选状态）"""
            if sel["rect"] is None and sel["sx"] is None:
                _show_crosshair()
                _update_crosshair(e.x, e.y)

        def on_enter(e: tk.Event) -> None:
            _show_crosshair()
            _update_crosshair(e.x, e.y)

        def on_leave(e: tk.Event) -> None:
            _hide_crosshair()

        def on_up(e: tk.Event) -> None:
            if sel["sx"] is not None:
                _crop(sel["sx"], sel["sy"], e.x, e.y)
            _cleanup()
            self._done.set()

        def on_cancel(e: tk.Event) -> None:
            self._result = None
            _cleanup()
            self._done.set()

        canvas.bind("<ButtonPress-1>", on_down)
        canvas.bind("<B1-Motion>", on_move)
        canvas.bind("<Motion>", on_motion)
        canvas.bind("<Enter>", on_enter)
        canvas.bind("<Leave>", on_leave)
        canvas.bind("<ButtonRelease-1>", on_up)
        canvas.bind("<ButtonPress-3>", on_cancel)
        freeze_overlay.bind("<Escape>", on_cancel)
        freeze_overlay.bind("<ButtonPress-3>", on_cancel)
        freeze_overlay.focus_force()
