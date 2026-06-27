"""SnapPaddleOCR - 设置窗口（Modern UI）"""

import os
import sys
import tkinter as tk
from tkinter import ttk
from ..config import config

_STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", ""),
    r"Microsoft\Windows\Start Menu\Programs\Startup",
)
_STARTUP_LNK = os.path.join(_STARTUP_DIR, "SnapPaddleOCR.lnk")


def _create_shortcut(target, link_path):
    """在 Windows 启动目录创建快捷方式"""
    try:
        import pythoncom
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(link_path)
        shortcut.TargetPath = target
        shortcut.WorkingDirectory = os.path.dirname(target)
        shortcut.Description = "SnapPaddleOCR · 截图速识"
        shortcut.Save()
        pythoncom.CoUninitialize()
        return True
    except Exception:
        return False


def _remove_shortcut(link_path):
    """删除启动目录快捷方式"""
    try:
        if os.path.exists(link_path):
            os.remove(link_path)
        return True
    except Exception:
        return False

C_PRIMARY   = "#1565C0"
C_PRIMARY_L = "#1E88E5"
C_BG        = "#F5F5F5"
C_SURFACE   = "#FFFFFF"
C_TEXT      = "#212121"
C_TEXT_SUB  = "#757575"
C_BORDER    = "#E0E0E0"


class SettingsWindow:
    """设置窗口"""

    def __init__(self, parent, font_family="Microsoft YaHei", on_save_hotkey=None):
        self._font = font_family
        self._on_save_hotkey = on_save_hotkey  # 保存后重新注册热键的回调

        self._dialog = tk.Toplevel(parent)
        self._dialog.title("SnapPaddleOCR · 设置")
        self._dialog.geometry("520x650")
        self._dialog.resizable(False, False)
        self._dialog.transient(parent)
        self._dialog.grab_set()
        self._dialog.configure(bg=C_BG)

        # ── 顶部标题 ──
        header = tk.Frame(self._dialog, bg=C_PRIMARY, height=44)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="设置", font=(self._font, 13, "bold"),
                 fg="white", bg=C_PRIMARY).pack(side=tk.LEFT, padx=16, pady=9)

        # ── 可滚动内容区 ──
        outer = tk.Frame(self._dialog, bg=C_BG)
        outer.pack(fill=tk.BOTH, expand=True)

        canvas_bg = tk.Canvas(outer, bg=C_BG, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas_bg.yview)
        scroll_frame = tk.Frame(canvas_bg, bg=C_BG)

        scroll_frame.bind("<Configure>",
                          lambda e: canvas_bg.configure(scrollregion=canvas_bg.bbox("all")))
        canvas_bg.create_window((0, 0), window=scroll_frame, anchor="nw", tags="inner")
        canvas_bg.configure(yscrollcommand=scrollbar.set)

        def _on_mw(event):
            canvas_bg.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas_bg.bind_all("<MouseWheel>", _on_mw)
        self._dialog.protocol("WM_DELETE_WINDOW", lambda: (
            canvas_bg.unbind_all("<MouseWheel>"), self._dialog.destroy()))

        canvas_bg.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ── 通用卡片 ──
        def _card(parent_outer, title):
            card = tk.Frame(parent_outer, bg=C_SURFACE,
                            highlightbackground=C_BORDER,
                            highlightthickness=1,
                            padx=16, pady=12)
            card.pack(fill=tk.X, padx=12, pady=(0, 10))
            tk.Label(card, text=title, font=(self._font, 11, "bold"),
                     fg=C_PRIMARY, bg=C_SURFACE).pack(anchor=tk.W, pady=(0, 8))
            return card

        self._entries = {}

        # ── 快捷键 ──
        card1 = _card(scroll_frame, "⌨  快捷键设置")
        tk.Label(card1, text="点击输入框后直接按下组合键即可设置",
                 font=(self._font, 8), fg=C_TEXT_SUB, bg=C_SURFACE).pack(anchor=tk.W, pady=(0, 6))
        for key, label, default in [
            ("screenshot_hotkey", "截图OCR", "ctrl+shift+f"),
            ("clipboard_hotkey", "剪贴板OCR", "ctrl+shift+g"),
            ("quick_ocr_hotkey", "快速OCR（不弹窗）", "ctrl+shift+d"),
        ]:
            row = tk.Frame(card1, bg=C_SURFACE)
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=label, font=(self._font, 10),
                     fg=C_TEXT, bg=C_SURFACE,
                     width=16, anchor=tk.W).pack(side=tk.LEFT)
            entry = ttk.Entry(row, font=(self._font, 10), width=22,
                             foreground=C_TEXT_SUB)
            entry.insert(0, config.get(key, default))
            entry.pack(side=tk.LEFT, padx=(4, 0))
            self._setup_hotkey_capture(entry)
            self._entries[key] = entry

        # ── OCR 参数 ──
        card2 = _card(scroll_frame, "🎯  OCR 参数")
        for key, label, default in [
            ("text_det_thresh", "检测阈值", 0.3),
            ("text_det_box_thresh", "文本框阈值", 0.6),
            ("text_rec_score_thresh", "识别置信度", 0.5),
        ]:
            row = tk.Frame(card2, bg=C_SURFACE)
            row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=label, font=(self._font, 10),
                     fg=C_TEXT, bg=C_SURFACE,
                     width=16, anchor=tk.W).pack(side=tk.LEFT)

            val = config.get(key, default)
            var = tk.DoubleVar(value=val)
            scale = ttk.Scale(row, from_=0.0, to=1.0, variable=var,
                              orient=tk.HORIZONTAL, length=180)
            scale.pack(side=tk.LEFT, padx=(4, 6))

            val_lbl = tk.Label(row, text=f"{val:.2f}",
                               font=(self._font, 9, "bold"),
                               fg=C_PRIMARY, bg=C_SURFACE,
                               width=4, anchor=tk.W)
            val_lbl.pack(side=tk.LEFT)

            def _tracer(lbl):
                return lambda *a: lbl.config(text=f"{var.get():.2f}")
            var.trace_add("write", _tracer(val_lbl))

            descs = {"text_det_thresh": "越低越敏感",
                     "text_det_box_thresh": "文本框筛选",
                     "text_rec_score_thresh": "低于此值过滤"}
            tk.Label(row, text=descs.get(key, ""),
                     font=(self._font, 8),
                     fg=C_TEXT_SUB, bg=C_SURFACE).pack(side=tk.LEFT, padx=(4, 0))
            self._entries[key] = var

        # ── 推理设置 ──
        card_infer = _card(scroll_frame, "⚡  推理设置")
        cpu_count = os.cpu_count() or 4
        row_infer = tk.Frame(card_infer, bg=C_SURFACE)
        row_infer.pack(fill=tk.X, pady=4)
        tk.Label(row_infer, text="CPU 线程数", font=(self._font, 10),
                 fg=C_TEXT, bg=C_SURFACE,
                 width=16, anchor=tk.W).pack(side=tk.LEFT)
        thread_vals = [str(i) for i in range(1, cpu_count + 1)]
        cur_threads = str(config.get("cpu_threads", cpu_count))
        if cur_threads not in thread_vals:
            cur_threads = str(cpu_count)
        self._cpu_threads_var = tk.StringVar(value=cur_threads)
        cb = ttk.Combobox(row_infer, textvariable=self._cpu_threads_var,
                          values=thread_vals, state="readonly",
                          font=(self._font, 10), width=6)
        cb.pack(side=tk.LEFT, padx=(4, 6))
        tk.Label(row_infer, text=f"  共 {cpu_count} 核，数值越大识别越快",
                 font=(self._font, 8),
                 fg=C_TEXT_SUB, bg=C_SURFACE).pack(side=tk.LEFT)

        # ── 输出设置 ──
        card3 = _card(scroll_frame, "📤  输出设置")
        self._auto_copy_var = tk.BooleanVar(value=config.get("auto_copy", True))
        ttk.Checkbutton(card3, text="自动复制结果到剪贴板",
                        variable=self._auto_copy_var).pack(anchor=tk.W, pady=2)
        self._show_toast_var = tk.BooleanVar(value=config.get("show_toast", True))
        ttk.Checkbutton(card3, text="屏幕下方显示识别内容提示（Toast）",
                        variable=self._show_toast_var).pack(anchor=tk.W, pady=2)
        self._show_window_var = tk.BooleanVar(value=config.get("show_result_window", True))
        ttk.Checkbutton(card3, text="识别后自动显示结果窗口",
                        variable=self._show_window_var).pack(anchor=tk.W, pady=2)

        # ── 界面设置 ──
        card4 = _card(scroll_frame, "🖥  界面设置")
        self._close_action_var = tk.StringVar(value=config.get("close_action", "minimize"))
        df = tk.Frame(card4, bg=C_SURFACE)
        df.pack(fill=tk.X)
        ttk.Radiobutton(df, text="最小化到托盘",
                        variable=self._close_action_var,
                        value="minimize").pack(anchor=tk.W, pady=2)
        ttk.Radiobutton(df, text="退出软件",
                        variable=self._close_action_var,
                        value="exit").pack(anchor=tk.W, pady=2)
        tk.Label(card4, text="主窗口关闭时的行为",
                 font=(self._font, 8), fg=C_TEXT_SUB, bg=C_SURFACE,
                 anchor=tk.W).pack(fill=tk.X, pady=(4, 0))

        # 开机自启
        self._autostart_var = tk.BooleanVar(value=config.get("autostart", False))
        ttk.Checkbutton(card4, text="开机自动启动",
                        variable=self._autostart_var).pack(anchor=tk.W, pady=(8, 2))

        # 启动时隐藏主窗口
        self._start_minimized_var = tk.BooleanVar(value=config.get("start_minimized", False))
        ttk.Checkbutton(card4, text="启动时隐藏主窗口（后台运行）",
                        variable=self._start_minimized_var).pack(anchor=tk.W, pady=2)

        # ── 排版规则 ──
        layout_options = {
            "raw":  "不做处理（逐段换行）",
            "none": "不换行（合并为一行）",
        }
        card5 = _card(scroll_frame, "📝  识别排版")
        self._layout_var = tk.StringVar(value="不做处理（逐段换行）")
        # 根据已保存的值初始化下拉框显示
        saved = config.get("result_layout", "raw")
        if saved in layout_options:
            self._layout_var.set(layout_options[saved])
        cb = ttk.Combobox(card5, textvariable=self._layout_var,
                          values=list(layout_options.values()),
                          state="readonly", font=(self._font, 10), width=34)
        cb.pack(fill=tk.X, pady=2)
        self._layout_options_map = layout_options
        cb.bind("<<ComboboxSelected>>", lambda e: None)

        # ── 底部按钮 ──
        btn_bar = tk.Frame(self._dialog, bg=C_SURFACE,
                           highlightbackground=C_BORDER,
                           highlightthickness=1, height=50)
        btn_bar.pack(fill=tk.X)
        btn_bar.pack_propagate(False)

        ttk.Button(btn_bar, text="  取消  ", command=self._dialog.destroy).pack(
            side=tk.RIGHT, padx=(0, 12), pady=9)

        save_btn = tk.Button(btn_bar, text="  保存设置  ",
                             font=(self._font, 10, "bold"),
                             fg="white", bg=C_PRIMARY,
                             activebackground=C_PRIMARY_L, activeforeground="white",
                             relief="flat", padx=16, pady=4, bd=0,
                             command=self._save)
        save_btn.pack(side=tk.RIGHT, padx=(0, 8), pady=9)

        def _on_enter(e):
            save_btn.config(bg=C_PRIMARY_L)
        def _on_leave(e):
            save_btn.config(bg=C_PRIMARY)
        save_btn.bind("<Enter>", _on_enter)
        save_btn.bind("<Leave>", _on_leave)

    # ── 快捷键按键捕捉 ──
    @staticmethod
    def _keysym_to_short(keysym):
        """tkinter keysym → 热键字符串中的键名"""
        k = keysym.lower()
        # 功能键
        if k.startswith('f') and k[1:].isdigit() and 1 <= int(k[1:]) <= 12:
            return k
        # 单字母 / 数字
        if (len(k) == 1 and k.isascii() and (k.isalpha() or k.isdigit())):
            return k
        # 特殊键映射
        mapping = {
            'space': 'space', 'escape': 'esc',
            'return': 'enter', 'backspace': 'backspace',
            'delete': 'delete', 'tab': 'tab',
            'up': 'up', 'down': 'down', 'left': 'left', 'right': 'right',
            'home': 'home', 'end': 'end',
            'prior': 'pageup', 'next': 'pagedown',
            'insert': 'insert', 'caps_lock': 'capslock',
            'minus': '-', 'equal': '=', 'comma': ',', 'period': '.',
            'slash': '/', 'semicolon': ';', 'apostrophe': "'",
            'bracketleft': '[', 'bracketright': ']', 'backslash': '\\',
            'grave': '`',
        }
        return mapping.get(k, k)

    @staticmethod
    def _setup_hotkey_capture(entry):
        """对 Entry 控件启用按键捕捉模式：点击后直接按组合键即完成设置"""
        cap = {'active': False, 'original': ''}

        def _get_modifier_state():
            """查询物理键盘修饰键状态（绕开 tkinter e.state 位掩码不可靠问题）"""
            mods = {'ctrl': False, 'alt': False, 'shift': False}
            try:
                import ctypes
                # Windows: GetKeyState 检测物理按键
                # 最高位为 1 表示当前按下（0x8000）
                VK_CONTROL = 0x11
                VK_MENU = 0x12  # Alt
                VK_SHIFT = 0x10
                VK_LCONTROL = 0xA2
                VK_RCONTROL = 0xA3
                VK_LMENU = 0xA4  # LAlt
                VK_RMENU = 0xA5  # RAlt
                VK_LSHIFT = 0xA0
                VK_RSHIFT = 0xA1

                def is_pressed(vk):
                    return ctypes.windll.user32.GetKeyState(vk) & 0x8000 != 0

                mods['ctrl'] = is_pressed(VK_CONTROL) or is_pressed(VK_LCONTROL) or is_pressed(VK_RCONTROL)
                mods['alt'] = is_pressed(VK_MENU) or is_pressed(VK_LMENU) or is_pressed(VK_RMENU)
                mods['shift'] = is_pressed(VK_SHIFT) or is_pressed(VK_LSHIFT) or is_pressed(VK_RSHIFT)
            except Exception:
                # 回退：用 e.state 检测（屏蔽 NumLock 干扰位）
                pass
            return mods

        def _on_focus_in(e):
            cap['active'] = True
            cap['original'] = entry.get().strip()
            # 进入捕捉模式：蓝字提示
            entry.configure(foreground=C_PRIMARY)
            if cap['original']:
                entry.selection_range(0, tk.END)
            else:
                entry.delete(0, tk.END)
                entry.insert(0, '按下组合键…')

        def _on_focus_out(e):
            cap['active'] = False
            current = entry.get().strip()
            # 如果没输入有效组合键，恢复原值
            if current in ('', '按下组合键…'):
                entry.delete(0, tk.END)
                entry.insert(0, cap['original'])
            entry.configure(foreground=C_TEXT_SUB)

        def _on_key(e):
            if not cap['active']:
                return

            keysym = e.keysym.lower()

            # 忽略纯修饰键（单独按下 Ctrl/Shift/Alt 不响应）
            if keysym in ('control_l', 'control_r', 'shift_l', 'shift_r',
                          'alt_l', 'alt_r', 'meta_l', 'meta_r',
                          'super_l', 'super_r', 'win_l', 'win_r'):
                return "break"

            # Escape：恢复原始值
            if keysym == 'escape':
                entry.delete(0, tk.END)
                entry.insert(0, cap['original'])
                return "break"

            # Backspace / Delete：清空
            if keysym in ('backspace', 'delete'):
                entry.delete(0, tk.END)
                return "break"

            # 检测修饰键状态（使用 Win32 API 直接查询物理键盘，不受 e.state 干扰）
            mods = _get_modifier_state()
            parts = []
            if mods['ctrl']:
                parts.append('ctrl')
            if mods['alt']:
                parts.append('alt')
            if mods['shift']:
                parts.append('shift')

            # 主键
            key_name = SettingsWindow._keysym_to_short(keysym)
            if not key_name:
                return "break"

            parts.append(key_name)
            entry.delete(0, tk.END)
            entry.insert(0, '+'.join(parts))
            return "break"

        entry.bind("<FocusIn>", _on_focus_in)
        entry.bind("<FocusOut>", _on_focus_out)
        entry.bind("<KeyPress>", _on_key)

    # ── 保存 ──
    def _save(self):
        try:
            for key, entry in self._entries.items():
                if isinstance(entry, tk.DoubleVar):
                    config.set(key, round(entry.get(), 2))
                else:
                    config.set(key, entry.get().strip())
            config.set("cpu_threads", int(self._cpu_threads_var.get()))
            config.set("auto_copy", self._auto_copy_var.get())
            config.set("show_toast", self._show_toast_var.get())
            config.set("show_result_window", self._show_window_var.get())
            config.set("close_action", self._close_action_var.get())
            config.set("autostart", self._autostart_var.get())
            config.set("start_minimized", self._start_minimized_var.get())
            # 排版值反向映射
            layout_display = self._layout_var.get()
            layout_key = "auto"
            for k, v in self._layout_options_map.items():
                if v == layout_display:
                    layout_key = k
                    break
            config.set("result_layout", layout_key)
            config.save()

            # 开机自启：创建/删除启动目录快捷方式
            self._handle_autostart()

            # 通知外部重新注册热键
            if self._on_save_hotkey:
                self._on_save_hotkey()
        finally:
            self._dialog.destroy()

    def _handle_autostart(self):
        """根据开机自启设置，创建或移除启动快捷方式"""
        from ..paths import PROJECT_ROOT
        import sys

        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.join(PROJECT_ROOT, "dist", "SnapPaddleOCR", "SnapPaddleOCR.exe")

        if self._autostart_var.get():
            if os.path.exists(exe_path):
                _create_shortcut(exe_path, _STARTUP_LNK)
        else:
            _remove_shortcut(_STARTUP_LNK)
