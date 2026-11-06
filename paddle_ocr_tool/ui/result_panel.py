"""SnapPaddleOCR - 识别结果卡片列表

管理主窗口中的识别结果卡片（时间戳 + 复制按钮 + 文字内容）。
带数量上限：超过上限自动销毁最旧的卡片，防止长时间运行时
Tk 控件与闭包无限累积导致内存持续增长。
从 main_window.py 拆分而来，专职"结果展示"单一职责。
"""

import tkinter as tk
from typing import Callable, List, Optional

from . import theme

# 结果卡片数量上限：既保证历史可查，又防止控件/文本无限累积占内存
MAX_CARDS = 50


class ResultPanel:
    """识别结果卡片面板（所有方法必须在 Tk 主线程中调用）"""

    def __init__(self, root: tk.Misc, parent: tk.Frame,
                 canvas: tk.Canvas, font_family: str,
                 on_status: Optional[Callable[[str], None]] = None) -> None:
        self._root = root
        self._font_family = font_family
        self._on_status = on_status
        self._cards: List[tk.Frame] = []
        self._seq = 0

        self._card_frame = tk.Frame(parent, bg=theme.SURFACE)
        self._canvas = canvas

        self._card_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._card_frame,
                             anchor=tk.NW, tags="inner")

        def _on_canvas_width(e: tk.Event) -> None:
            canvas.itemconfig("inner", width=e.width)
        canvas.bind("<Configure>", _on_canvas_width)

    @property
    def frame(self) -> tk.Frame:
        """内部卡片容器（供外部绑定滚轮等事件）"""
        return self._card_frame

    def clear(self) -> None:
        """清空所有卡片并释放引用"""
        for card in self._cards:
            card.destroy()
        self._cards.clear()
        self._seq = 0

    def add(self, text: str, timestamp: Optional[str] = None,
            tag: Optional[str] = None) -> None:
        """追加一条识别记录卡片

        Args:
            text: 卡片正文
            timestamp: 时间戳文本
            tag: 可选来源标签（如 "扫码·QRCode"），默认显示序号
        """
        self._seq += 1
        self._create_card(text, timestamp, tag)
        self._evict_oldest_if_needed()
        # 滚动到底部
        self._root.after(50, lambda: self._canvas.yview_moveto(1.0))

    def get_all_text(self) -> str:
        """获取全部卡片文本（按时间顺序合并）"""
        texts = [card._card_text for card in self._cards
                 if getattr(card, "_card_text", "")]
        return "\n".join(texts)

    def _evict_oldest_if_needed(self) -> None:
        """超过上限时销毁最旧的卡片，释放控件与文本引用"""
        while len(self._cards) > MAX_CARDS:
            oldest = self._cards.pop(0)
            oldest.destroy()

    def _create_card(self, text: str, timestamp: Optional[str],
                     tag: Optional[str] = None) -> None:
        cnt = self._seq

        # ── 卡片容器 ──
        card = tk.Frame(self._card_frame, bg=theme.SURFACE,
                        highlightbackground=theme.BORDER,
                        highlightthickness=1,
                        padx=14, pady=10)
        card.pack(fill=tk.X, padx=10, pady=(0, 8))
        self._cards.append(card)

        # 正文缓存（供全部复制使用）
        card._card_text = text

        # ── 顶部元信息行 ──
        header = tk.Frame(card, bg=theme.SURFACE)
        header.pack(fill=tk.X)

        if tag:
            # 扫码等特殊来源：用标签替代序号
            tk.Label(header, text=f"[{tag}]",
                     font=(self._font_family, 8, "bold"),
                     fg=theme.PRIMARY, bg=theme.SURFACE).pack(side=tk.LEFT)
        else:
            tk.Label(header, text=f"#{cnt}",
                     font=(self._font_family, 8),
                     fg=theme.TEXT_SECONDARY, bg=theme.SURFACE).pack(side=tk.LEFT)

        tk.Label(header,
                 text=timestamp or "",
                 font=(self._font_family, 9, "bold"),
                 fg=theme.PRIMARY, bg=theme.SURFACE).pack(side=tk.LEFT, padx=(8, 0))

        # 独立复制按钮
        copy_btn = tk.Button(header, text=" 复制 ",
                             font=(self._font_family, 8),
                             fg=theme.PRIMARY, bg=theme.SURFACE,
                             activebackground=theme.HOVER,
                             activeforeground=theme.PRIMARY,
                             relief="flat", bd=0,
                             cursor="hand2",
                             command=lambda t=text: self._copy(t))
        copy_btn.pack(side=tk.RIGHT)
        copy_btn.bind("<Enter>",
                      lambda e, b=copy_btn: b.config(bg=theme.HOVER))
        copy_btn.bind("<Leave>",
                      lambda e, b=copy_btn: b.config(bg=theme.SURFACE))

        # ── 分割线 ──
        sep = tk.Frame(card, bg=theme.BORDER, height=1)
        sep.pack(fill=tk.X, pady=(6, 6))

        # ── 文字内容 ──
        body = tk.Label(card, text=text,
                        font=(self._font_family, 11),
                        fg=theme.TEXT, bg=theme.SURFACE,
                        justify=tk.LEFT, anchor=tk.W,
                        wraplength=600)
        body.pack(fill=tk.X, anchor=tk.W)

        # 宽度适配：父容器尺寸确定后更新 wraplength
        def _update_wrap() -> None:
            pw = self._canvas.winfo_width()
            if pw > 60:
                body.configure(wraplength=pw - 48)
        self._root.after(80, _update_wrap)

        # 正文区域点击复制
        body.bind("<Button-1>", lambda e, t=text: self._copy(t))
        body.bind("<Enter>", lambda e, b=body: b.config(bg=theme.HOVER))
        body.bind("<Leave>", lambda e, b=body: b.config(bg=theme.SURFACE))

        # 整张卡片点击复制
        card.bind("<Button-1>", lambda e, t=text: self._copy(t))
        for child in (header, sep):
            child.bind("<Button-1>", lambda e, t=text: self._copy(t))

        # 卡片上鼠标滚轮绑定（canvas 内嵌 frame 的事件隔离问题）
        on_wheel = theme.make_wheel_scroller(self._canvas)
        for w in (card, header, body, sep):
            w.bind("<MouseWheel>", on_wheel)

    def _copy(self, text: str) -> None:
        if theme.copy_to_clipboard(self._root, text):
            if self._on_status:
                self._on_status("已复制")
