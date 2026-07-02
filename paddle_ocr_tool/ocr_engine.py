# SnapPaddleOCR 截图文字识别工具
# OCR引擎模块 - 封装PaddleOCR的OCR识别功能

import logging
import os
import shutil

from pathlib import Path

# 在导入 paddle 前确保环境变量已设置
from .env_config import setup_paddle_env
from .paths import CACHE_DIR

setup_paddle_env()

logger = logging.getLogger("SnapPaddleOCR.OCR")


def _is_corrupted_model_cache_error(exc):
    """判断异常是否由模型缓存损坏导致"""
    msg = str(exc)
    return (
        "inference.yml" in msg or "inference.pdmodel" in msg
    ) and ".paddlex_cache" in msg


def _clear_paddlex_model_cache():
    """清理 PaddleX 官方模型缓存目录，触发重新下载"""
    cache_dir = Path(
        os.environ.get("PADDLE_PDX_CACHE_HOME", CACHE_DIR)
    )
    models_dir = cache_dir / "official_models"
    if models_dir.exists():
        try:
            shutil.rmtree(models_dir)
            logger.warning("已清理损坏的模型缓存: %s", models_dir)
        except Exception as e:
            logger.error("清理模型缓存失败: %s", e)


class OCREngine:
    """OCR引擎，封装PaddleOCR"""

    def __init__(self, config=None):
        self._ocr = None
        self._config = config or {}
        self._initialized = False
        self._error = None

    @property
    def is_initialized(self):
        return self._initialized

    @property
    def error_message(self):
        return self._error

    def initialize(self, **kwargs):
        """初始化OCR引擎 · CPU 模式，若模型缓存损坏则自动清理重试"""
        try:
            # 重要：再次确保 env 在 paddle 导入前设置
            os.environ["FLAGS_use_mkldnn"] = "0"
            os.environ["FLAGS_enable_pir_api"] = "0"

            from paddleocr import PaddleOCR

            # 导入后再次尝试通过 paddle API 关闭 OneDNN
            try:
                import paddle
                if hasattr(paddle, "set_flags"):
                    paddle.set_flags({"FLAGS_use_mkldnn": False})
                elif hasattr(paddle, "core"):
                    pass  # paddle.core 在 3.x 中 API 已变
            except Exception:
                pass

            params = {
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
                "text_det_limit_type": kwargs.get(
                    "text_det_limit_type", "max"
                ),
                "text_det_thresh": kwargs.get("text_det_thresh", 0.3),
                "text_det_box_thresh": kwargs.get("text_det_box_thresh", 0.6),
                "text_det_unclip_ratio": kwargs.get(
                    "text_det_unclip_ratio", 1.5
                ),
                "text_rec_score_thresh": kwargs.get(
                    "text_rec_score_thresh", 0.5
                ),
                # ── CPU 模式：必须关闭 MKLDNN ──
                "device": kwargs.get("device", "cpu"),
                "enable_mkldnn": kwargs.get("enable_mkldnn", False),
                "cpu_threads": kwargs.get("cpu_threads", 4),
            }

            logger.info(
                "OCR 运行配置: device=%s, enable_mkldnn=%s, cpu_threads=%s",
                params["device"],
                params["enable_mkldnn"],
                params["cpu_threads"],
            )

            # 首次尝试
            try:
                self._ocr = PaddleOCR(**params)
            except FileNotFoundError as e:
                if _is_corrupted_model_cache_error(e):
                    logger.warning(
                        "检测到模型缓存损坏，正在清理后重试: %s", e
                    )
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

    def recognize(self, image):
        """识别图片中的文字

        Args:
            image: PIL Image对象 或 图片文件路径

        Returns:
            dict: {"code": 100, "data": [...]} 或 {"code": 400, "data": "错误信息"}
        """
        if not self._initialized or not self._ocr:
            return {"code": 400, "data": self._error or "OCR引擎未初始化"}

        try:
            from PIL import Image

            if isinstance(image, Image.Image):
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".png", delete=False
                )
                tmp_path = tmp.name
                tmp.close()
                image.save(tmp_path)
                input_path = tmp_path
                need_cleanup = True
            elif isinstance(image, str):
                input_path = image
                need_cleanup = False
            else:
                return {"code": 400, "data": "不支持的图片类型"}

            # 执行OCR
            results = self._ocr.predict(input_path)

            if need_cleanup:
                try:
                    os.unlink(input_path)
                except OSError:
                    pass

            if not results:
                return {"code": 100, "data": []}

            # PaddleX 结果格式解析
            ocr_data = []
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

            return {"code": 100, "data": ocr_data}

        except Exception as e:
            return {"code": 400, "data": f"OCR识别失败: {e}"}

    def recognize_bytes(self, image_bytes):
        """识别图片字节数据"""
        from PIL import Image
        import io

        try:
            image = Image.open(io.BytesIO(image_bytes))
            return self.recognize(image)
        except Exception as e:
            return {"code": 400, "data": f"图片解析失败: {e}"}

    def close(self):
        """关闭引擎释放资源"""
        if self._ocr:
            try:
                self._ocr.close()
            except Exception:
                pass
            self._ocr = None
            self._initialized = False

    @staticmethod
    def check_environment():
        """检查运行环境"""
        issues = []
        for pkg_name in ["paddleocr", "paddle", "PIL"]:
            try:
                if pkg_name == "PIL":
                    from PIL import Image

                    issues.append(
                        (pkg_name, Image.__version__, True)
                    )
                else:
                    mod = __import__(pkg_name)
                    issues.append(
                        (
                            pkg_name,
                            getattr(mod, "__version__", "?"),
                            True,
                        )
                    )
            except ImportError:
                issues.append((pkg_name, "未安装", False))
        return issues
