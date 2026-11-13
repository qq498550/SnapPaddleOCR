# PaddleOCR 截图文字识别工具
# 智能排版模块 - 判断 OCR 行是"同段视觉折行"还是"真实段落分隔"并自动合并
#
# 纯本地实现（无网络、无第三方依赖），利用识别项自带的 box 四点坐标做
# 几何分析，结合行尾标点、行首缩进、行宽断行位置、行距、语义连贯性等
# 信号，把被截图强制分行的文本行归并为自然段落。
#
# 公开接口：
#   format_smart(items, threshold=4.0) -> str | None
#     返回排版后的文本；无法可靠分析（缺坐标/单行/疑似多栏等）时
#     返回 None，由调用方降级为逐行输出。

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median
from typing import Any, List, Optional, Sequence, Tuple

# ── 字符特征集合 ──
# 中文句末终止符：出现即强分段信号
_CN_TERMINATORS = set("。！？；…”）》〉】")
# 中文句中延续符（逗号/顿号/冒号/破折号/前引号等）：出现即折行信号
_CN_CONTINUATIONS = set("，、：—…“（《〈【‘‘")
# CJK 判定（含全角标点）
_CJK_RANGES = (
    (0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x3000, 0x303F),
    (0xFF00, 0xFFEF),
)
# 英文句末终止符
_EN_TERMINATORS = set(".!?")
# 英文延续标点
_EN_CONTINUATIONS = set(",;:")
# 成对开闭符号（用于未闭合检测）
_PAIRS = {"(": ")", "（": "）", "[": "]", "【": "】",
          "《": "》", "〈": "〉", "“": "”", "‘": "’"}

# 行首项目符号/编号：列表项必须保留独立行
_LIST_MARKER = re.compile(
    r"^\s*([•‣◦·▪▫◦◦\-–—*+]+|"
    r"\(?\d{1,3}\s*[.、)）]\s*|"
    r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]|"
    r"[一二三四五六七八九十百]+\s*[、.．])"
)
# 行首列表标记（保守判定：编号类要求后面还有内容）
_WORD_CHAR = re.compile(r"[A-Za-z0-9]")


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


@dataclass
class _Line:
    """视觉行：由 y 区间重叠的识别项归并而成"""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def h(self) -> float:
        return max(self.y1 - self.y0, 1.0)

    @property
    def w(self) -> float:
        return max(self.x1 - self.x0, 1.0)


def _bbox(box: Any) -> Optional[Tuple[float, float, float, float]]:
    """box 四点多边形 → (x0, y0, x1, y1)；格式非法返回 None"""
    try:
        pts = [(float(p[0]), float(p[1])) for p in box]
        if len(pts) < 2:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)
    except (TypeError, ValueError, IndexError):
        return None


def _join_two(prev: str, nxt: str) -> str:
    """按连接规则拼接两段文本

    - 上一行尾是英文连字符 → 剥除直连（跨行断词）
    - 两侧均为 ASCII 词字符 → 补一个空格（英文单词边界）
    - 中文尾 → 英文/数字首 → 补一个空格（中英交界）
    - 其余（中文相邻）→ 直连
    """
    if prev.endswith("-") and _WORD_CHAR.match(prev[-2:-1] or " ") \
            and _WORD_CHAR.match(nxt[:1] or " "):
        return prev[:-1] + nxt
    if prev and nxt:
        if _WORD_CHAR.match(prev[-1]) and _WORD_CHAR.match(nxt[0]):
            return prev + " " + nxt
        # 中文（含全角标点）结尾接 ASCII 词 → 补空格提升可读性
        if _is_cjk(prev[-1]) and _WORD_CHAR.match(nxt[0]):
            return prev + " " + nxt
    return prev + nxt


def _join_texts(texts: Sequence[str]) -> str:
    out = ""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        out = _join_two(out, t) if out else t
    return out


def cluster_lines(items: List[dict]) -> Optional[List[_Line]]:
    """把识别项聚类为视觉行：y 区间重叠的项归为一行，行内按 x 排序

    返回 None 表示数据不适合几何分析（调用方应降级为逐行输出）。
    """
    entries: List[Tuple[Tuple[float, float, float, float], str]] = []
    for it in items:
        text = str(it.get("text", "")).strip()
        if not text:
            continue
        bbox = _bbox(it.get("box"))
        if bbox is None:
            return None  # 缺坐标 → 降级
        entries.append((bbox, text))
    if not entries:
        return []
    if len(entries) == 1:
        (x0, y0, x1, y1), text = entries[0]
        return [_Line(text, x0, y0, x1, y1)]

    entries.sort(key=lambda e: (e[0][1], e[0][0]))

    lines: List[_Line] = []
    cur: List[Tuple[Tuple[float, float, float, float], str]] = []
    wide_gap_rows = 0  # 行内出现"远大于字高的水平空隙"的行数（多栏特征）

    def _flush() -> None:
        nonlocal wide_gap_rows
        if not cur:
            return
        cur.sort(key=lambda e: e[0][0])
        h = median(b[3] - b[1] for b, _ in cur)
        # 行内项之间水平空隙超过 2 倍字高 → 疑似多栏/表格布局
        for a, b in zip(cur, cur[1:]):
            if b[0][0] - a[0][2] > 2.0 * max(h, 1.0):
                wide_gap_rows += 1
                break
        lines.append(_Line(
            _join_texts([t for _, t in cur]),
            min(b[0] for b, _ in cur), min(b[1] for b, _ in cur),
            max(b[2] for b, _ in cur), max(b[3] for b, _ in cur),
        ))
        cur.clear()

    for bbox, text in entries:
        if not cur:
            cur.append((bbox, text))
            continue
        # 与当前行 y 区间的重叠率（相对较矮一方）
        cy0, cy1 = min(b[1] for b, _ in cur), max(b[3] for b, _ in cur)
        inter = min(cy1, bbox[3]) - max(cy0, bbox[1])
        shorter = min(cy1 - cy0, bbox[3] - bbox[1])
        if shorter > 0 and inter / shorter > 0.5:
            cur.append((bbox, text))
        else:
            _flush()
            cur.append((bbox, text))
    _flush()

    if lines and len(lines) >= 3 and wide_gap_rows / len(lines) > 0.4:
        return None  # 疑似多栏/表格，安全降级
    lines.sort(key=lambda l: l.y0)
    return lines


def _unclosed_pairs(text: str) -> int:
    """未闭合的开括号/引号计数（正数表示有未闭合，倾向折行）"""
    depth = 0
    for ch in text:
        if ch in _PAIRS:
            depth += 1
        elif ch in _PAIRS.values() and depth > 0:
            depth -= 1
    return max(depth, 0)


def _starts_list(text: str) -> bool:
    return bool(_LIST_MARKER.match(text))


def _end_is_terminated(prev: _Line, nxt: Optional[_Line]) -> bool:
    """上行尾是否为"句末终止"（中英文分别判定）"""
    t = prev.text.rstrip()
    if not t:
        return False
    last = t[-1]
    if _is_cjk(last):
        return last in _CN_TERMINATORS
    # 英文：句末标点 + 下一行以大写字母/数字开头 才视为终止
    if last in _EN_TERMINATORS:
        if nxt is None:
            return True
        return bool(nxt.text) and (nxt.text[0].isupper()
                                   or nxt.text[0].isdigit())
    return False


def analyze_paragraphs(lines: List[_Line],
                       threshold: float = 4.0) -> List[List[_Line]]:
    """把视觉行序列切分为段落组（每组内的行合并为一段）

    决策逻辑：
    1. 强规则否决（优先级最高）：
       - 上行尾为英文连字符 → 必合并（跨行断词）
       - 下行首为项目符号/编号 → 保留独立行
       - 上行尾终止标点 且 行距显著大于平均 → 必分段
       - 上行为"短行且行高显著偏大"（标题特征）→ 保留独立行
    2. 其余按加权信号评分，得分 ≥ threshold 判为同段折行，否则分段。
    """
    n = len(lines)
    if n <= 1:
        return [lines[:]]

    pitches = [lines[i + 1].y0 - lines[i].y0 for i in range(n - 1)]
    pitches = [max(p, 1.0) for p in pitches]
    med_pitch = median(pitches)
    med_h = median(l.h for l in lines)
    # 列宽参考：行宽 85 分位（折行段的行通常顶到列边界）
    widths = sorted(l.w for l in lines)
    ref_width = widths[int(0.85 * (len(widths) - 1))]

    groups: List[List[_Line]] = []
    cur: List[_Line] = [lines[0]]
    para_left = lines[0].x0  # 当前段落基准左缘

    for i in range(n - 1):
        prev, nxt = lines[i], lines[i + 1]
        pitch = pitches[i]

        # ── 强规则否决 ──
        # 1) 跨行断词：英文行尾连字符 → 必合并
        if prev.text.rstrip().endswith("-") \
                and _WORD_CHAR.match(prev.text.rstrip()[-2:-1] or " "):
            cur.append(nxt)
            continue
        # 2) 下行首为项目符号/编号 → 新组（列表项独立）
        if _starts_list(nxt.text):
            groups.append(cur)
            cur = [nxt]
            para_left = nxt.x0
            continue
        # 3) 终止标点 + 大行距 → 必分段
        gap_ratio = pitch / med_pitch
        if _end_is_terminated(prev, nxt) and gap_ratio > 1.3:
            groups.append(cur)
            cur = [nxt]
            para_left = nxt.x0
            continue
        # 4) 标题特征：明显短 + 行高显著大于中位 → 独立行
        if prev.h > med_h * 1.3 and prev.w < ref_width * 0.6:
            groups.append(cur)
            cur = [nxt]
            para_left = nxt.x0
            continue

        # ── 加权信号评分（正分 = 折行/合并信号）──
        score = 0.0
        # 行尾字符特征
        tail = prev.text.rstrip()[-1:] if prev.text.rstrip() else ""
        if tail:
            if _is_cjk(tail):
                if tail in _CN_TERMINATORS:
                    score -= 4          # 中文终止符
                elif tail in _CN_CONTINUATIONS:
                    score += 2          # 逗号/顿号/冒号等延续符
                else:
                    score += 3          # 无标点（句子被截断）
            else:
                if tail in _EN_CONTINUATIONS:
                    score += 2
                elif tail in _EN_TERMINATORS:
                    score -= 3 if gap_ratio <= 1.15 else 0
                elif _WORD_CHAR.match(tail):
                    score += 2
                    # 英文词尾 + 下行小写开头 → 明显跨行断句
                    if nxt.text[:1].islower():
                        score += 3
        # 括号/引号未闭合
        if _unclosed_pairs(prev.text) > 0:
            score += 3
        # 行首缩进：与段落基准左缘对齐 → 折行；明显缩进 → 新段
        indent = nxt.x0 - para_left
        if abs(indent) < 0.35 * med_h:
            score += 2
        elif indent > 1.5 * med_h:
            score -= 4
        elif indent < -0.6 * med_h:
            score -= 1                  # 左凸出（悬挂缩进），弱分段信号
        # 行宽与断行位置：满行 → 自然折行；明显短行 → 段末
        if prev.w > ref_width * 0.88:
            score += 2
        elif prev.w < ref_width * 0.55:
            score -= 2
        # 行距：接近平均行距 → 同段；显著变大 → 新段
        if gap_ratio <= 1.2:
            score += 2
        elif gap_ratio >= 1.6:
            score -= 4

        if score >= threshold:
            cur.append(nxt)             # 判定：同一自然段的视觉折行
        else:
            groups.append(cur)          # 判定：真实段落分隔
            cur = [nxt]
            para_left = nxt.x0

    groups.append(cur)
    return groups


def format_smart(items: List[dict], threshold: float = 4.0) -> Optional[str]:
    """智能排版入口：items（OcrItem 列表）→ 段落化文本

    返回 None 表示无法可靠分析（缺坐标/多栏布局等），调用方应降级
    为逐行输出（raw 行为）。
    """
    try:
        lines = cluster_lines(items)
        if not lines:
            return None
        groups = analyze_paragraphs(lines, threshold)
        return "\n".join(_join_texts([l.text for l in g]) for g in groups)
    except Exception:
        return None  # 任何异常均安全降级
