# SnapPaddleOCR - OCR 引擎模块：封装 PaddleOCR 的初始化 / 识别 / 释放

import gc
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np

from .env_config import apply_thread_env, setup_paddle_env
from .paths import CACHE_DIR

setup_paddle_env()

logger = logging.getLogger("SnapPaddleOCR.OCR")

# 识别结果数据项类型：{"box": [[x, y], ...], "text": str, "score": float}
OcrItem = Dict[str, Any]
# 识别结果统一返回格式：code=100 成功 / 400 失败
OcrResult = Dict[str, Any]

# PaddleOCR predict() 支持的输入类型
PredictInput = Union[str, np.ndarray]


def logical_cpu_count() -> int:
    """本机逻辑处理器核心数"""
    return os.cpu_count() or 4


def clamp_cpu_threads(value: Any) -> int:
    """将 CPU 线程数限制在 [1, 逻辑核数] 区间

    线程数超过物理可调度核心会导致 OpenMP 线程自旋争抢，
    实测超配（24 线程 / 16 核）反而使识别慢 3 倍以上。
    """
    logical = logical_cpu_count()
    try:
        threads = int(value)
    except (TypeError, ValueError):
        threads = logical
    return max(1, min(threads, logical))


def _is_corrupted_model_cache_error(exc: Exception) -> bool:
    """判断异常是否由模型缓存损坏导致"""
    msg = str(exc)
    return (
        "inference.yml" in msg or "inference.pdmodel" in msg
    ) and ".paddlex_cache" in msg


def _clear_paddlex_model_cache() -> None:
    """清理 PaddleX 官方模型缓存目录，触发重新下载"""
    cache_dir = Path(os.environ.get("PADDLE_PDX_CACHE_HOME", CACHE_DIR))
    models_dir = cache_dir / "official_models"
    if models_dir.exists():
        try:
            shutil.rmtree(models_dir)
            logger.warning("已清理损坏的模型缓存: %s", models_dir)
        except Exception as e:
            logger.error("清理模型缓存失败: %s", e)


class OCREngine:
    """OCR 引擎：单实例常驻，封装 PaddleOCR 的初始化、识别与释放"""

    def __init__(self) -> None:
        self._ocr: Any = None
        self._initialized = False
        self._error: Optional[str] = None

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def error_message(self) -> Optional[str]:
        return self._error

    @staticmethod
    def _build_params(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """将用户配置映射为 PaddleOCR 构造参数

        cpu_threads 会被 clamp 到 [1, 逻辑核数]：超配会导致线程
        自旋争抢，CPU 占用反而上不去且识别显著变慢。
        """
        raw_threads = kwargs.get("cpu_threads", logical_cpu_count())
        threads = clamp_cpu_threads(raw_threads)
        if threads != raw_threads:
            logger.warning(
                "cpu_threads=%s 超出本机逻辑核数 %s，已自动调整为 %s",
                raw_threads, logical_cpu_count(), threads,
            )
        return {
            "lang": kwargs.get("language", "ch"),
            "ocr_version": kwargs.get("ocr_version", "PP-OCRv6"),
            "use_doc_orientation_classify": kwargs.get(
                "use_doc_orientation", False
            ),
            "use_doc_unwarping": False,
            "use_textline_orientation": kwargs.get(
                "use_textline_orientation", True
            ),
            "text_det_limit_side_len": kwargs.get(
                "text_det_limit_side_len", 960
            ),
            "text_det_limit_type": kwargs.get("text_det_limit_type", "max"),
            "text_det_thresh": kwargs.get("text_det_thresh", 0.3),
            "text_det_box_thresh": kwargs.get("text_det_box_thresh", 0.6),
            "text_det_unclip_ratio": kwargs.get("text_det_unclip_ratio", 1.5),
            "text_rec_score_thresh": kwargs.get("text_rec_score_thresh", 0.5),
            # ── CPU 模式：必须关闭 MKLDNN ──
            "device": kwargs.get("device", "cpu"),
            "enable_mkldnn": kwargs.get("enable_mkldnn", False),
            "cpu_threads": threads,
        }

    def initialize(self, **kwargs: Any) -> bool:
        """初始化 OCR 引擎（CPU 模式），若模型缓存损坏则自动清理重试"""
        try:
            params = self._build_params(kwargs)

            # 重要：必须在 paddle 首次导入前设置环境
            os.environ["FLAGS_use_mkldnn"] = "0"
            os.environ["FLAGS_enable_pir_api"] = "0"
            # OMP 固定 1 线程：CPU 并行统一由 cpu_threads 控制，避免双线程池争抢
            apply_thread_env()

            from paddleocr import PaddleOCR

            # 导入后再次尝试通过 paddle API 关闭 OneDNN
            try:
                import paddle
                if hasattr(paddle, "set_flags"):
                    paddle.set_flags({"FLAGS_use_mkldnn": False})
            except Exception:
                pass

            logger.info(
                "OCR 运行配置: device=%s, enable_mkldnn=%s, cpu_threads=%s",
                params["device"],
                params["enable_mkldnn"],
                params["cpu_threads"],
            )

            try:
                self._ocr = PaddleOCR(**params)
            except FileNotFoundError as e:
                if _is_corrupted_model_cache_error(e):
                    logger.warning("检测到模型缓存损坏，正在清理后重试: %s", e)
                    _clear_paddlex_model_cache()
                    self._ocr = PaddleOCR(**params)
                else:
                    raise

            self._initialized = True
            self._error = None
            return True

        except ImportError as e:
            self._error = f"PaddleOCR未安装: {e}"
            return False
        except Exception as e:
            self._error = f"OCR引擎初始化失败: {e}"
            return False

    @staticmethod
    def _to_predict_input(image: Union[str, np.ndarray, Any]) -> Optional[PredictInput]:
        """将外部输入归一化为 predict() 支持的类型

        支持文件路径与 PIL.Image。PIL.Image 直接转为 numpy 数组
        在内存中传递给 PaddleOCR，避免"写临时 PNG 文件"带来的
        磁盘 I/O 与异常路径下的临时文件残留。
        """
        from PIL import Image

        if isinstance(image, str):
            return image
        if isinstance(image, Image.Image):
            return np.asarray(image.convert("RGB"))
        return None

    def recognize(self, image: Union[str, np.ndarray, Any]) -> OcrResult:
        """识别图片中的文字

        Args:
            image: 图片文件路径、PIL.Image 或 numpy 数组

        Returns:
            {"code": 100, "data": [...]} 成功；
            {"code": 400, "data": "错误信息"} 失败
        """
        if not self._initialized or not self._ocr:
            return {"code": 400, "data": self._error or "OCR引擎未初始化"}

        try:
            predict_input = self._to_predict_input(image)
            if predict_input is None:
                return {"code": 400, "data": "不支持的图片类型"}

            results = self._ocr.predict(predict_input)
            if not results:
                return {"code": 100, "data": []}

            return {"code": 100, "data": self._parse_results(results)}

        except Exception as e:
            logger.exception("OCR 识别失败")
            return {"code": 400, "data": f"OCR识别失败: {e}"}

    @staticmethod
    def _parse_results(results: Any) -> List[OcrItem]:
        """解析 PaddleX 结果格式为统一数据项列表"""
        ocr_data: List[OcrItem] = []
        for page_result in results:
            if not isinstance(page_result, dict):
                continue

            rec_texts = page_result.get("rec_texts", [])
            rec_scores = page_result.get("rec_scores", [])
            dt_polys = page_result.get("dt_polys", [])

            for i in range(len(rec_texts)):
                text = rec_texts[i] if i < len(rec_texts) else ""
                score = (
                    float(rec_scores[i])
                    if i < len(rec_scores)
                    else 0.0
                )
                poly = (
                    dt_polys[i].tolist()
                    if i < len(dt_polys)
                    else []
                )

                if text and text.strip():
                    ocr_data.append(
                        {
                            "box": poly,
                            "text": text,
                            "score": round(score, 4),
                        }
                    )
        return ocr_data

    def reload(self, **kwargs: Any) -> bool:
        """按新参数重建引擎（用于设置变更后即时生效，无需重启程序）"""
        self.close()
        return self.initialize(**kwargs)

    def close(self) -> None:
        """关闭引擎释放资源（模型与推理器引用置空并触发 GC 回收）"""
        if self._ocr:
            try:
                self._ocr.close()
            except Exception:
                pass
            self._ocr = None
            self._initialized = False
            # 主动回收推理框架持有的临时对象，降低退出前内存峰值
            gc.collect()
