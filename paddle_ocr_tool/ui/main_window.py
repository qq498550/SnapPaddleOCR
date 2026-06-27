"""SnapPaddleOCR - 主窗口（Modern UI）"""

import os
import tkinter as tk
from tkinter import ttk
import threading

# ── 配色 ──
C_PRIMARY   = "#1565C0"
C_PRIMARY_L = "#1E88E5"
C_PRIMARY_D = "#0D47A1"
C_BG        = "#F5F5F5"
C_SURFACE   = "#FFFFFF"
C_TEXT      = "#212121"
C_TEXT_SUB  = "#757575"
C_BORDER    = "#E0E0E0"
C_HOVER     = "#E3F2FD"


def _setup_style(root, font_family):
    """配置全局 ttk 样式"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except:
        pass

    style.configure(".", background=C_BG, foreground=C_TEXT,
                    font=(font_family, 10))
    style.configure("TButton",
                    background=C_SURFACE, foreground=C_TEXT,
                    borderwidth=1, focusthickness=0, focuscolor="none",
                    padding=(12, 4))
    style.map("TButton",
              background=[("active", C_HOVER), ("pressed", C_BORDER)],
              relief=[("pressed", "sunken")])

    style.configure("Primary.TButton",
                    background=C_PRIMARY, foreground="white",
                    borderwidth=0, focuscolor="none",
                    padding=(14, 6))
    style.map("Primary.TButton",
              background=[("active", C_PRIMARY_L), ("pressed", C_PRIMARY_D)],
              foreground=[("active", "white"), ("pressed", "white")])

    style.configure("Secondary.TButton",
                    background=C_SURFACE, foreground=C_TEXT_SUB,
                    borderwidth=1, focusthickness=0, focuscolor="none",
                    padding=(10, 3))
    style.map("Secondary.TButton",
              background=[("active", C_HOVER)],
              foreground=[("active", C_PRIMARY)])

    style.configure("Sub.TLabel", font=(font_family, 9),
                    background=C_BG, foreground=C_TEXT_SUB)
    style.configure("TSeparator", background=C_BORDER)
    style.configure("Status.TLabel", font=(font_family, 9),
                    background=C_BORDER, foreground=C_TEXT_SUB,
                    relief="solid", borderwidth=1, padding=(8, 5))
    style.configure("TEntry", font=(font_family, 10),
                    fieldbackground=C_SURFACE, foreground=C_TEXT,
                    borderwidth=1, padding=(6, 3))
    return style


class MainWindow:
    """主界面窗口"""

    def __init__(self):
        self._root = None
        self._status_label = None
        self._on_close_callback = None
        self._on_screenshot_cb = None
        self._on_clipboard_cb = None
        self._on_save_settings_cb = None
        self._btn_scr = None   # 截图OCR按钮引用
        self._btn_clp = None   # 剪贴板OCR按钮引用
        self._font_family = "TkDefaultFont"
        self._sel_result = None
        self._sel_event = None

    def set_callbacks(self, on_screenshot=None, on_clipboard=None,
                      screenshot_hotkey_str=None, clipboard_hotkey_str=None,
                      on_save_settings=None):
        self._on_screenshot_cb = on_screenshot
        self._on_clipboard_cb = on_clipboard
        self._screenshot_hotkey_str = screenshot_hotkey_str or "Ctrl+Shift+F"
        self._clipboard_hotkey_str = clipboard_hotkey_str or "Ctrl+Shift+G"
        self._on_save_settings_cb = on_save_settings

    @staticmethod
    def _capture_fullscreen_physical():
        """抓取全屏并缩放到虚拟桌面尺寸，确保与 tkinter 坐标系对齐

        PIL.ImageGrab.grab() 内部会临时切换 DPI 感知，返回物理像素图
        （如 3840×2160）。通过 GetSystemMetrics 获取虚拟桌面尺寸
        （如 1707×960），将物理图 resize 到虚拟尺寸后，坐标与 tkinter
        overlay 完全一致。

        Returns:
            full_img — 虚拟坐标尺寸的 PIL.Image 或 None
        """
        import ctypes
        from PIL import Image, ImageGrab

        user32 = ctypes.windll.user32

        # 虚拟桌面尺寸（DPI 无感知返回虚拟坐标）
        vs_w = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        vs_h = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN

        if vs_w <= 0 or vs_h <= 0:
            return None

        try:
            # PIL 抓取物理像素全屏
            full_img = ImageGrab.grab(all_screens=True)

            # 缩放至虚拟桌面尺寸，与 tkinter 坐标对齐
            if full_img.size != (vs_w, vs_h):
                full_img = full_img.resize((vs_w, vs_h), Image.LANCZOS)
        except Exception:
            return None

        return full_img

    def update_hotkey_display(self):
        """设置变更后刷新工具栏快捷键按钮文字（线程安全）"""
        from config import config

        def _fmt(h):
            return "+".join(w.capitalize() for w in h.split("+"))

        sh = _fmt(config.get("screenshot_hotkey", "ctrl+shift+f"))
        ch = _fmt(config.get("clipboard_hotkey", "ctrl+shift+g"))
        self._screenshot_hotkey_str = sh
        self._clipboard_hotkey_str = ch

        if self._root and self._btn_scr:
            self._root.after(0, lambda: (
                self._btn_scr.config(text=f"  📷  截图OCR  ({sh})  "),
                self._btn_clp.config(text=f"  📋  剪贴板OCR  ({ch})  ")
            ))

    # =================================================================
    def show(self, on_close=None, start_minimized=False):
        self._on_close_callback = on_close

        self._root = tk.Tk()
        self._root.title("SnapPaddleOCR · 截图速识")
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
        self._root.configure(bg=C_BG)

        # ── 字体检测 ──
        if self._font_exists("Microsoft YaHei"):
            self._font_family = "Microsoft YaHei"
        elif self._font_exists("微软雅黑"):
            self._font_family = "微软雅黑"
        elif self._font_exists("SimHei"):
            self._font_family = "SimHei"
        else:
            self._font_family = "TkDefaultFont"

        _setup_style(self._root, self._font_family)

        # ── 顶部标题栏 ──
        header = tk.Frame(self._root, bg=C_PRIMARY, height=48)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="SnapPaddleOCR", font=(self._font_family, 14, "bold"),
                 fg="white", bg=C_PRIMARY).pack(side=tk.LEFT, padx=16, pady=10)
        tk.Label(header, text="截图速识", font=(self._font_family, 10),
                 fg="#B3D4FC", bg=C_PRIMARY).pack(side=tk.LEFT, pady=10)

        # ── 工具栏 ──
        tb = tk.Frame(self._root, bg=C_SURFACE, height=44)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)

        ctn = tk.Frame(tb, bg=C_SURFACE)
        ctn.pack(side=tk.LEFT, padx=10)

        def _mkbtn(parent, text, cmd, primary=False):
            st = "Primary.TButton" if primary else "TButton"
            btn = ttk.Button(parent, text=text, command=cmd, style=st)
            btn.pack(side=tk.LEFT, padx=(0, 6), pady=5)
            return btn

        self._btn_scr = _mkbtn(ctn, f"  📷  截图OCR  ({self._screenshot_hotkey_str})  ",
                               self._on_screenshot, primary=True)
        self._btn_clp = _mkbtn(ctn, f"  📋  剪贴板OCR  ({self._clipboard_hotkey_str})  ",
                               self._on_clipboard, primary=True)
        _mkbtn(ctn, "  🗑  清空  ", self._on_clear)
        _mkbtn(ctn, "  📄  复制结果  ", self._on_copy)

        r_ctn = tk.Frame(tb, bg=C_SURFACE)
        r_ctn.pack(side=tk.RIGHT, padx=10)
        ttk.Button(r_ctn, text="  ⚙  设置  ", command=self._on_settings,
                   style="Secondary.TButton").pack(side=tk.RIGHT, padx=(4, 0), pady=5)

        # ── 内容区（卡片列表）──
        cf = tk.Frame(self._root, bg=C_SURFACE)
        cf.pack(fill=tk.BOTH, expand=True)

        self._card_canvas = tk.Canvas(cf, bg=C_SURFACE, highlightthickness=0)
        self._card_scrollbar = ttk.Scrollbar(cf, orient=tk.VERTICAL,
                                             command=self._card_canvas.yview)
        self._card_frame = tk.Frame(self._card_canvas, bg=C_SURFACE)

        self._card_frame.bind("<Configure>",
            lambda e: self._card_canvas.configure(
                scrollregion=self._card_canvas.bbox("all")))
        self._card_canvas.create_window((0, 0), window=self._card_frame,
                                        anchor=tk.NW, tags="inner")

        def _on_card_canvas_width(e):
            self._card_canvas.itemconfig("inner", width=e.width)
        self._card_canvas.bind("<Configure>", _on_card_canvas_width)

        self._card_canvas.configure(yscrollcommand=self._card_scrollbar.set)
        self._card_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._card_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 鼠标滚轮滚动（canvas + 内部 frame 均绑定，覆盖卡片区域）
        def _on_mw(event):
            self._card_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        for w in (self._card_canvas, self._card_frame):
            w.bind("<MouseWheel>", _on_mw)
        self._card_canvas.bind("<Enter>", lambda e: self._card_canvas.focus_set())
        self._card_canvas.bind("<Leave>", lambda e: self._root.focus_set())

        # 序列号
        self._result_count = 0

        # ── 状态栏 ──
        self._status_label = tk.Label(
            self._root,
            text="正在初始化...",
            anchor=tk.W,
            padx=14, pady=5,
            font=(self._font_family, 9),
            fg=C_TEXT_SUB, bg=C_BORDER,
            relief="flat")
        self._status_label.pack(fill=tk.X)

        # ── 事件 ──
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.bind("<Control-f>", lambda e: self._on_screenshot())
        self._root.bind("<Control-g>", lambda e: self._on_clipboard())

        # 启动时隐藏主窗口
        if start_minimized:
            self._root.withdraw()

        self._root.mainloop()

    def _font_exists(self, family):
        try:
            from tkinter import font
            return family.lower() in [f.lower() for f in font.families()]
        except:
            return True

    # ===== 截图区域选择（画面冻结机制）=====
    def start_region_selection(self):
        """启动区域选择：冻结画面后等待用户框选"""
        if not self._root:
            return None
        self._sel_result = None

        # 抓取全屏并冻结当前画面（resize 到虚拟坐标尺寸）
        full_img = MainWindow._capture_fullscreen_physical()
        if full_img is None:
            return None

        self._sel_event = threading.Event()
        self._root.after(0, lambda: self._create_selection_overlay(full_img))
        self._sel_event.wait(timeout=120)
        self._sel_event = None
        return self._sel_result

    def _create_selection_overlay(self, full_img):
        """全屏画面冻结局域选择

        将触发瞬间的全屏画面冻结为静态背景，覆盖暗色遮罩，
        用户可在静止画面上精准框选区域。完成后自动解除冻结。
        """
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

        def _update_crosshair(x, y):
            """更新十字线位置"""
            canvas.coords(cross_v, x, 0, x, sh)
            canvas.coords(cross_h, 0, y, sw, y)

        def _show_crosshair():
            """显示十字线"""
            for item in canvas.find_withtag("cross"):
                canvas.itemconfigure(item, state="normal")

        def _hide_crosshair():
            """隐藏十字线"""
            for item in canvas.find_withtag("cross"):
                canvas.itemconfigure(item, state="hidden")

        # 初始隐藏，鼠标进入 overlay 后才显示
        _hide_crosshair()

        def _cleanup():
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

        def _crop(sx, sy, ex, ey):
            """在冻结画面上精准裁切"""
            l, t = min(sx, ex), min(sy, ey)
            r, b = max(sx, ex), max(sy, ey)
            if r - l < 5 or b - t < 5:
                self._sel_result = None
                return
            try:
                self._sel_result = full_img.crop((l, t, r, b))
            except Exception:
                self._sel_result = None

        def on_down(e):
            sel["sx"], sel["sy"] = e.x, e.y
            _hide_crosshair()  # 拖选时隐藏十字线
            # 选中区域高亮（橙框描边）
            sel["rect"] = canvas.create_rectangle(
                e.x, e.y, e.x, e.y,
                outline="#FF5722", width=3,
            )

        def on_move(e):
            if sel["rect"] and sel["sx"] is not None:
                canvas.coords(sel["rect"], sel["sx"], sel["sy"], e.x, e.y)

        def on_motion(e):
            """鼠标移动时更新十字坐标线（仅在非拖选状态）"""
            if sel["rect"] is None and sel["sx"] is None:
                _show_crosshair()
                _update_crosshair(e.x, e.y)

        def on_enter(e):
            """鼠标进入 overlay 时显示十字线"""
            _show_crosshair()
            _update_crosshair(e.x, e.y)

        def on_leave(e):
            """鼠标离开 overlay 时隐藏十字线"""
            _hide_crosshair()

        def on_up(e):
            if sel["sx"] is not None:
                _crop(sel["sx"], sel["sy"], e.x, e.y)
            _cleanup()
            if self._sel_event:
                self._sel_event.set()

        def on_cancel(e):
            self._sel_result = None
            _cleanup()
            if self._sel_event:
                self._sel_event.set()

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

    # ===== 界面操作 =====
    def _on_screenshot(self):
        if self._on_screenshot_cb:
            self.hide()                       # 隐藏主窗口，避免出现在截图中
            self._root.update_idletasks()     # 立即刷新
            self._root.after(500, self._on_screenshot_cb)  # 延迟 0.5s 等窗口完全消失

    def _on_clipboard(self):
        if self._on_clipboard_cb:
            self._on_clipboard_cb()

    def _on_clear(self):
        for w in self._card_frame.winfo_children():
            w.destroy()
        self._result_count = 0

    def _on_copy(self):
        texts = []
        for card in self._card_frame.winfo_children():
            body = getattr(card, "_card_text", "")
            if body:
                texts.append(body)
        all_text = "\n".join(texts)
        if all_text:
            self._root.clipboard_clear()
            self._root.clipboard_append(all_text)
            self.set_status("已复制全部到剪贴板")

    def _on_settings(self):
        from .settings_window import SettingsWindow
        SettingsWindow(self._root, font_family=self._font_family,
                       on_save_hotkey=self._on_save_settings_cb)

    def _on_hide(self):
        self.hide()

    def _on_close(self):
        if self._on_close_callback:
            self._on_close_callback()
        elif self._root:
            self._root.destroy()

    def add_result(self, text, timestamp=None):
        """添加一条识别记录卡片

        每条卡片包含: 时间戳 + 独立复制按钮 + 文字内容
        """
        if not self._root:
            return
        self._root.after(0, lambda: self._create_card(text, timestamp))

    def _create_card(self, text, timestamp):
        self._result_count += 1
        cnt = self._result_count

        # ── 卡片容器 ──
        card = tk.Frame(self._card_frame, bg=C_SURFACE,
                        highlightbackground=C_BORDER,
                        highlightthickness=1,
                        padx=14, pady=10)
        card.pack(fill=tk.X, padx=10, pady=(0, 8))

        # 正文缓存（供全部复制使用）
        card._card_text = text

        # ── 顶部元信息行 ──
        header = tk.Frame(card, bg=C_SURFACE)
        header.pack(fill=tk.X)

        tk.Label(header, text=f"#{cnt}",
                 font=(self._font_family, 8),
                 fg=C_TEXT_SUB, bg=C_SURFACE).pack(side=tk.LEFT)

        tk.Label(header,
                 text=timestamp if timestamp else "",
                 font=(self._font_family, 9, "bold"),
                 fg=C_PRIMARY, bg=C_SURFACE).pack(side=tk.LEFT, padx=(8, 0))

        # 独立复制按钮
        def _copy_this(t=text):
            self._root.clipboard_clear()
            self._root.clipboard_append(t)
            self.set_status("已复制")

        copy_btn = tk.Button(header, text=" 复制 ",
                             font=(self._font_family, 8),
                             fg=C_PRIMARY, bg=C_SURFACE,
                             activebackground=C_HOVER,
                             activeforeground=C_PRIMARY,
                             relief="flat", bd=0,
                             cursor="hand2",
                             command=_copy_this)
        copy_btn.pack(side=tk.RIGHT)
        copy_btn.bind("<Enter>",
                      lambda e, b=copy_btn: b.config(bg=C_HOVER))
        copy_btn.bind("<Leave>",
                      lambda e, b=copy_btn: b.config(bg=C_SURFACE))

        # ── 分割线 ──
        sep = tk.Frame(card, bg=C_BORDER, height=1)
        sep.pack(fill=tk.X, pady=(6, 6))

        # ── 文字内容 ──
        body = tk.Label(card, text=text,
                        font=(self._font_family, 11),
                        fg=C_TEXT, bg=C_SURFACE,
                        justify=tk.LEFT, anchor=tk.W,
                        wraplength=600)
        body.pack(fill=tk.X, anchor=tk.W)

        # 宽度适配：父容器尺寸确定后更新 wraplength
        def _update_wrap():
            pw = self._card_canvas.winfo_width()
            if pw > 60:
                body.configure(wraplength=pw - 48)
        self._root.after(80, _update_wrap)

        # 正文区域点击复制
        def _on_body_click(e, t=text):
            self._root.clipboard_clear()
            self._root.clipboard_append(t)
            self.set_status("已复制")
        body.bind("<Button-1>", _on_body_click)
        body.bind("<Enter>", lambda e, b=body: b.config(bg=C_HOVER))
        body.bind("<Leave>", lambda e, b=body: b.config(bg=C_SURFACE))

        # 整张卡片点击复制
        card.bind("<Button-1>",
                  lambda e, t=text: _on_body_click(e, t))
        for child in [header, sep]:
            child.bind("<Button-1>",
                       lambda e, t=text: _on_body_click(e, t))

        # 卡片上鼠标滚轮绑定（canvas 内嵌 frame 的事件隔离问题）
        def _card_scroll(event):
            self._card_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        for w in (card, header, body, sep):
            w.bind("<MouseWheel>", _card_scroll)

        # 滚动到底部
        self._root.after(50, lambda: self._card_canvas.yview_moveto(1.0))

    # 保持兼容旧接口
    def append_text(self, text):
        self.add_result(text)

    def show_toast(self, text, duration=4000):
        """屏幕下方半透明提示浮窗（类似 Umi-OCR 识别提示）

        Args:
            text: 显示的文本内容（多行自动截断为最多 3 行）
            duration: 自动关闭毫秒数，0 表示不自动关闭
        """
        if not self._root or not text:
            return

        self._root.after(0, lambda: self._show_toast_ui(text, duration))

    def _show_toast_ui(self, text, duration):
        """在主线程中创建并显示 Toast"""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return
        display = "  |  ".join(lines[:3])
        if len(lines) > 3:
            display += f"  ...  (+{len(lines) - 3}行)"
        max_chars = 80
        if len(display) > max_chars:
            display = display[:max_chars - 3] + "..."

        toast = tk.Toplevel(self._root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)

        # 配色（深色半透明）
        bg_color = "#DF9C9C"
        fg_color = "#FFFFFF"

        lbl = tk.Label(
            toast, text=display,
            font=(self._font_family, 11),
            fg=fg_color, bg=bg_color,
            wraplength=600,
            justify=tk.LEFT,
            padx=18, pady=10,
        )
        lbl.pack()

        toast.configure(bg=bg_color)
        toast.update_idletasks()

        # 定位到屏幕底部居中
        w = toast.winfo_width()
        h = toast.winfo_height()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = (sw - w) // 2
        y = sh - h - 60
        toast.geometry(f"+{x}+{y}")

        # 半透明
        try:
            toast.attributes("-alpha", 0.92)
        except Exception:
            pass

        # 点击关闭
        def _dismiss(e=None):
            try:
                toast.destroy()
            except Exception:
                pass
        lbl.bind("<Button-1>", _dismiss)
        toast.bind("<Button-1>", _dismiss)

        # 自动关闭
        if duration > 0:
            toast.after(duration, _dismiss)

    def set_text(self, text):
        self._on_clear()
        if text and self._root:
            self._root.after(0, lambda: self._create_card(
                text, ""))


    def set_status(self, text):
        if self._status_label and self._root:
            self._root.after(0, lambda: self._status_label.config(text=str(text)))

    def hide(self):
        if self._root:
            self._root.withdraw()

    def show_window(self):
        if self._root:
            self._root.after(0, lambda: (
                self._root.deiconify(),
                self._root.lift(),
                self._root.focus_force()))

    @property
    def is_visible(self):
        return self._root and self._root.winfo_exists() and self._root.state() != "withdrawn"

    def close(self):
        if self._root:
            try:
                self._root.quit()
                self._root.destroy()
            except:
                pass
            self._root = None
