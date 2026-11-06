# SnapPaddleOCR - 二维码 / 条形码扫描模块
# 优先使用 zxing-cpp（支持 QR/一维码/DataMatrix 等全格式），
# 未安装时退回 OpenCV 内置 QR 检测器，保证功能可用。

import logging
from dataclasses import dataclass
from typing import Any, List, Optional

logger = logging.getLogger("SnapPaddleOCR.CodeScanner")


@dataclass(frozen=True)
class DetectedCode:
    """单条扫码结果"""
    text: str
    format: str          # 码制名称，如 QRCode / Code128 / EAN13
    is_2d: bool = False  # 是否为二维码类（2D）


class CodeScanner:
    """二维码 / 条形码扫描器（懒加载解码后端，扫描失败不影响主流程）"""

    def __init__(self) -> None:
        self._zxing: Optional[Any] = None
        self._backend_ready = False
        self._backend: str = ""

    @property
    def backend(self) -> str:
        """当前解码后端名称：zxing / opencv / none"""
        self._ensure_backend()
        return self._backend

    def _ensure_backend(self) -> None:
        """首次使用时加载解码后端"""
        if self._backend_ready:
            return
        self._backend_ready = True
        try:
            import zxingcpp
            self._zxing = zxingcpp
            self._backend = "zxing"
            logger.info("扫码后端：zxing-cpp")
            return
        except ImportError:
            pass
        try:
            import cv2  # noqa: F401
            self._backend = "opencv"
            logger.warning("未安装 zxing-cpp，退回 OpenCV（仅支持二维码）")
        except ImportError:
            self._backend = "none"
            logger.warning("无可用的扫码后端，二维码/条形码识别已禁用")

    def scan(self, image: Any) -> List[DetectedCode]:
        """解析图片中的全部二维码 / 条形码

        Args:
            image: PIL.Image 图片

        Returns:
            去重后的识别结果列表；未识别到或出错时返回空列表
        """
        if image is None:
            return []

        self._ensure_backend()
        try:
            if self._backend == "zxing":
                return self._scan_zxing(image)
            if self._backend == "opencv":
                return self._scan_opencv(image)
        except Exception as e:
            logger.warning("扫码失败: %s", e)
        return []

    def _scan_zxing(self, image: Any) -> List[DetectedCode]:
        assert self._zxing is not None
        results: List[DetectedCode] = []
        for barcode in self._zxing.read_barcodes(image):
            text = (barcode.text or "").strip()
            if not text:
                continue
            fmt = str(barcode.format).replace("BarcodeFormat.", "")
            results.append(DetectedCode(
                text=text,
                format=fmt,
                is_2d="QR" in fmt or "DataMatrix" in fmt or "Aztec" in fmt,
            ))
        return self._dedupe(results)

    def _scan_opencv(self, image: Any) -> List[DetectedCode]:
        """OpenCV 兜底方案：仅支持二维码"""
        import cv2
        import numpy as np

        arr = np.asarray(image.convert("RGB"))
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        detector = cv2.QRCodeDetector()
        text, _, _ = detector.detectAndDecode(bgr)
        text = (text or "").strip()
        return [DetectedCode(text=text, format="QRCode", is_2d=True)] if text else []

    @staticmethod
    def _dedupe(codes: List[DetectedCode]) -> List[DetectedCode]:
        """按 (码制, 内容) 去重，保持识别顺序"""
        seen = set()
        unique: List[DetectedCode] = []
        for code in codes:
            key = (code.format, code.text)
            if key in seen:
                continue
            seen.add(key)
            unique.append(code)
        return unique
