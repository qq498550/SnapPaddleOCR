"""SnapPaddleOCR - 通用工具函数（与 UI 无关）"""

from typing import Iterator, Optional


def format_hotkey_for_display(hotkey: str) -> str:
    """将 'ctrl+shift+f' 格式转为 'Ctrl+Shift+F' 显示格式"""
    return "+".join(w.capitalize() for w in hotkey.split("+"))


def iter_nonempty_lines(text: str, limit: Optional[int] = None) -> Iterator[str]:
    """按行迭代非空文本（去除首尾空白），可限制返回条数"""
    count = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            count += 1
            if limit is not None and count > limit:
                return
            yield stripped
