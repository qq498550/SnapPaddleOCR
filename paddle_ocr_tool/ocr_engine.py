# SnapPaddleOCR - OCR 引擎模块：封装 PaddleOCR 的初始化 / 识别 / 释放

import gc
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

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


# ── 模型档位注册表 ──
# 轻量档模型随安装包内置（同步到用户缓存目录，离线可用）；
# 标准档体积大（约 133MB），不内嵌，设置中选择该档位时才联网下载。
# size_mb 用于首次下载提示，实际大小以官方发布为准。
MODEL_PROFILES: Dict[str, Dict[str, Any]] = {
    "lite": {
        "label": "轻量（速度快，推荐）",
        "det": "PP-OCRv4_mobile_det",
        "rec": "PP-OCRv4_mobile_rec",
        "size_mb": 16,
    },
    "standard": {
        "label": "标准（精度更高，体积较大）",
        "det": "PP-OCRv6_medium_det",
        "rec": "PP-OCRv6_medium_rec",
        "size_mb": 133,
    },
}

DEFAULT_PROFILE = "lite"

# 文字行方向分类子模型（use_textline_orientation 开启时使用，约 6.5MB）
TEXTLINE_MODEL = "PP-LCNet_x1_0_textline_ori"

# 档位模型名对以下语言通用；其余语言退回按 lang/ocr_version 自动选模型
_PROFILE_SUPPORTED_LANGS = {"ch", "chinese_cht", "en", "japan"}


def profile_models(profile: str) -> List[str]:
    """返回档位对应的模型目录名列表"""
    conf = MODEL_PROFILES.get(profile) or MODEL_PROFILES[DEFAULT_PROFILE]
    return [conf["det"], conf["rec"]]


def profile_label(profile: str) -> str:
    """档位中文名称"""
    conf = MODEL_PROFILES.get(profile) or MODEL_PROFILES[DEFAULT_PROFILE]
    return str(conf["label"])


def profile_size_mb(profile: str) -> int:
    """档位模型首次下载大小（MB）"""
    conf = MODEL_PROFILES.get(profile) or MODEL_PROFILES[DEFAULT_PROFILE]
    return int(conf["size_mb"])


def models_dir() -> Path:
    """PaddleX 官方模型缓存目录"""
    return Path(os.environ.get("PADDLE_PDX_CACHE_HOME", CACHE_DIR)) / "official_models"


def has_packaged_models() -> bool:
    """本地是否已有任意已下载模型（用于判断是否首次运行）"""
    d = models_dir()
    try:
        return d.is_dir() and any(d.iterdir())
    except OSError:
        return False


def missing_models(profile: str, use_textline_orientation: bool = False) -> List[str]:
    """返回该档位尚未下载到本地的模型名列表"""
    d = models_dir()
    names = profile_models(profile)
    if use_textline_orientation:
        names = names + [TEXTLINE_MODEL]
    return [name for name in names if not (d / name).is_dir()]


def bundled_models_dir() -> Path:
    """安装包内置模型目录（打包时随包分发的轻量档模型）"""
    from .paths import PROJECT_ROOT

    return Path(PROJECT_ROOT) / ".paddlex_cache" / "official_models"


def has_bundled_models() -> bool:
    """安装包是否内置了模型"""
    d = bundled_models_dir()
    try:
        return d.is_dir() and any(d.iterdir())
    except OSError:
        return False


def sync_bundled_models(
    profile: str, use_textline_orientation: bool = False
) -> List[str]:
    """将安装包内置模型同步到用户缓存目录，返回同步后仍缺失的模型

    打包后的安装目录可能只读（Program Files），且 PaddleX 只支持
    单一缓存目录，因此内置模型在首次运行时复制到用户缓存目录
    （约 16MB，本地复制秒级完成），保证默认轻量档完全离线可用。
    """
    missing = missing_models(profile, use_textline_orientation)
    if not missing or not has_bundled_models():
        return missing

    bundled = bundled_models_dir()
    target = models_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return missing

    copied = False
    for name in missing:
        src = bundled / name
        if not src.is_dir():
            continue
        try:
            shutil.copytree(src, target / name, dirs_exist_ok=True)
            copied = True
            logger.info("已从安装包同步内置模型: %s", name)
        except OSError as e:
            logger.warning("同步内置模型失败 %s: %s", name, e)

    return missing_models(profile, use_textline_orientation) if copied else missing


# ── 模型下载镜像（不使用 PaddleX 的源探测，网络受限环境更可靠） ──
MODEL_MIRRORS = (
    "https://paddle-model-ecology.bj.bcebos.com/paddlex/"
    "official_inference_model/paddle3.0.0/{name}_infer.tar",
    "https://paddle-model-ecology.cdn.bcebos.com/paddlex/"
    "official_inference_model/paddle3.0.0/{name}_infer.tar",
)

# 备选：ModelScope 逐文件直连（与 BOS 为不同 CDN，BOS 被拦截时仍可用）
MODELSCOPE_FILE_URL = (
    "https://www.modelscope.cn/api/v1/models/PaddlePaddle/{name}/repo"
    "?Revision=master&FilePath={file}"
)
MODEL_FILES = ("inference.json", "inference.yml", "inference.pdiparams")


def _notify(progress_cb: Optional[Callable[[str], None]], msg: str) -> None:
    """向 UI 回调进度（回调异常不影响下载）"""
    if progress_cb is None:
        return
    try:
        progress_cb(msg)
    except Exception:
        pass


def _cache_root() -> Path:
    """PaddleX 缓存根目录（含 official_models）"""
    return Path(os.environ.get("PADDLE_PDX_CACHE_HOME", CACHE_DIR))


def _extract_model_tar(tar_path: Path, name: str) -> bool:
    """解压官方模型 tar 到 official_models/<name>"""
    import tarfile

    work = _cache_root() / f".{name}.unpack"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(tar_path) as tf:
            try:
                tf.extractall(work, filter="data")
            except TypeError:  # Python < 3.11.4 无 filter 参数
                tf.extractall(work)
        inner = work / f"{name}_infer"
        if not inner.is_dir():
            dirs = [d for d in work.iterdir() if d.is_dir()]
            inner = dirs[0] if dirs else work
        target = models_dir() / name
        shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(inner), str(target))
        return (target / "inference.json").is_file() or (
            target / "inference.yml"
        ).is_file()
    except Exception as e:
        logger.warning("解压模型失败 %s: %s", name, e)
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)
        tar_path.unlink(missing_ok=True)


def download_model_from_modelscope(
    name: str,
    progress_cb: Optional[Callable[[str], None]] = None,
    attempts: int = 2,
) -> bool:
    """从 ModelScope 逐文件下载模型（BOS 不可达时的独立兜底通道）"""
    try:
        import requests
    except ImportError:
        return False

    target = models_dir() / name
    if target.is_dir():
        return True
    work = _cache_root() / f".{name}.files"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    try:
        for filename in MODEL_FILES:
            url = MODELSCOPE_FILE_URL.format(name=name, file=filename)
            ok = False
            for attempt in range(1, attempts + 1):
                try:
                    _notify(progress_cb, f"正在下载{name}/{filename}（{attempt}/{attempts}）…")
                    with requests.get(url, stream=True, timeout=(10, 60)) as resp:
                        resp.raise_for_status()
                        total = int(resp.headers.get("Content-Length") or 0)
                        done = 0
                        step = 0
                        with open(work / filename, "wb") as fh:
                            for chunk in resp.iter_content(1024 * 256):
                                if not chunk:
                                    continue
                                fh.write(chunk)
                                done += len(chunk)
                                if total and filename.endswith(".pdiparams"):
                                    pct = int(done * 100 / total)
                                    if pct >= step + 10:
                                        step = pct - pct % 10
                                        _notify(
                                            progress_cb,
                                            f"正在下载{name} {pct}%"
                                            f"（{done / 1048576:.0f}/"
                                            f"{total / 1048576:.0f} MB）",
                                        )
                    if (work / filename).stat().st_size < 100:
                        raise IOError("文件内容异常")
                    ok = True
                    break
                except Exception as e:
                    logger.warning(
                        "ModelScope 下载失败（%s，第 %s 次）: %s", filename, attempt, e
                    )
                    if attempt < attempts:
                        time.sleep(2)
            if not ok:
                return False

        if (work / "inference.pdiparams").stat().st_size < 1024 * 1024:
            logger.warning("ModelScope 模型权重异常: %s", name)
            return False
        shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(work), str(target))
        logger.info("模型就绪（ModelScope）: %s", name)
        return True
    except Exception as e:
        logger.warning("ModelScope 下载模型失败 %s: %s", name, e)
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def download_model_from_mirror(
    name: str,
    progress_cb: Optional[Callable[[str], None]] = None,
    attempts: int = 2,
) -> bool:
    """从官方镜像直接下载模型（流式 + 重试 + 解压），成功返回 True

    不依赖 PaddleX 的模型源探测逻辑：在部分网络环境下 PaddleX
    依次尝试 HuggingFace/AIStudio/ModelScope/BOS 全部失败后会直接
    放弃（No model source is available），因此这里自行下载兜底。
    """
    target = models_dir() / name
    if target.is_dir():
        return True
    try:
        import requests
    except ImportError as e:
        logger.warning("缺少 requests，无法直接下载模型: %s", e)
        return False

    root = _cache_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("创建缓存目录失败 %s: %s", root, e)
        return False

    tar_path = root / f".{name}.download.tar"
    for url_tpl in MODEL_MIRRORS:
        url = url_tpl.format(name=name)
        for attempt in range(1, attempts + 1):
            try:
                _notify(progress_cb, f"正在下载{name}（{attempt}/{attempts}）…")
                logger.info("开始下载模型 %s: %s", name, url)
                with requests.get(url, stream=True, timeout=(10, 60)) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("Content-Length") or 0)
                    done = 0
                    step = 0
                    with open(tar_path, "wb") as fh:
                        for chunk in resp.iter_content(1024 * 256):
                            if not chunk:
                                continue
                            fh.write(chunk)
                            done += len(chunk)
                            if total:
                                pct = int(done * 100 / total)
                                if pct >= step + 10:
                                    step = pct - pct % 10
                                    _notify(
                                        progress_cb,
                                        f"正在下载{name} {pct}%"
                                        f"（{done / 1048576:.0f}/"
                                        f"{total / 1048576:.0f} MB）",
                                    )
                size_mb = tar_path.stat().st_size / 1048576
                if size_mb < 1:
                    raise IOError(f"下载文件异常（{size_mb:.2f} MB）")
                logger.info("下载完成 %s（%.1f MB），开始解压", name, size_mb)
                if _extract_model_tar(tar_path, name):
                    logger.info("模型就绪: %s", name)
                    return True
                raise IOError("解压后缺少 inference 配置")
            except Exception as e:
                logger.warning("镜像下载失败（%s，第 %s 次）: %s", url, attempt, e)
                tar_path.unlink(missing_ok=True)
                if attempt < attempts:
                    time.sleep(2)

    # BOS 全部失败：换 ModelScope 独立通道再试
    logger.warning("BOS 镜像均不可用，尝试 ModelScope 直连下载: %s", name)
    return download_model_from_modelscope(name, progress_cb)


def ensure_profile_models(
    profile: str,
    use_textline_orientation: bool = False,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> List[str]:
    """确保档位模型存在（内置模型 → BOS 镜像 → ModelScope），返回仍缺失的模型"""
    missing = missing_models(profile, use_textline_orientation)
    if not missing:
        return []
    logger.info("档位 %s 缺少模型: %s，尝试镜像下载", profile, missing)
    for name in missing:
        download_model_from_mirror(name, progress_cb)
    return missing_models(profile, use_textline_orientation)


def is_corrupted_model_cache_error(exc: Exception) -> bool:
    """判断异常是否由模型缓存损坏导致"""
    msg = str(exc)
    return (
        "inference.yml" in msg or "inference.pdmodel" in msg
    ) and ("official_models" in msg or ".paddlex_cache" in msg)


def is_download_source_error(exc: Exception) -> bool:
    """判断异常是否由模型下载源不可用导致（多为网络瞬时故障）"""
    msg = str(exc)
    return (
        "No model source is available" in msg
        or "download model" in msg
        or "Model source" in msg
    )


def _is_corrupted_model_cache_error(exc: Exception) -> bool:
    """兼容旧内部调用名"""
    return is_corrupted_model_cache_error(exc)



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
        # 下载进度回调（由界面层注入，用于更新状态栏）
        self._progress: Optional[Callable[[str], None]] = None

    def set_progress_callback(
        self, callback: Optional[Callable[[str], None]]
    ) -> None:
        """注入模型下载进度回调（UI 线程安全由调用方保证）"""
        self._progress = callback

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

        params: Dict[str, Any] = {
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
            # CPU 推理：OneDNN 在 paddlex 3.x + PIR 执行器下不可用，必须显式关闭
            "device": kwargs.get("device", "cpu"),
            "enable_mkldnn": kwargs.get("enable_mkldnn", False),
            "cpu_threads": threads,
        }

        lang = kwargs.get("language", "ch")
        profile = kwargs.get("model_profile", DEFAULT_PROFILE)
        if lang in _PROFILE_SUPPORTED_LANGS:
            # 常见语言：直接指定模型名，确保档位与缓存检测一一对应
            names = profile_models(profile)
            params["text_detection_model_name"] = names[0]
            params["text_recognition_model_name"] = names[1]
        else:
            # 其他语言交由 PaddleOCR 按语言/版本自行选择模型
            params["lang"] = lang
            params["ocr_version"] = kwargs.get("ocr_version", "PP-OCRv6")
        return params

    def initialize(self, **kwargs: Any) -> bool:
        """初始化 OCR 引擎（CPU 模式），若模型缓存损坏则自动清理重试

        OneDNN(MKLDNN) 加速默认开启；若初始化失败则自动回退到
        无 OneDNN 模式重建，保证功能可用。
        """
        try:
            params = self._build_params(kwargs)

            # 模型准备：内置模型已同步，缺失的档位直接走镜像下载，
            # 不依赖 PaddleX 的源探测（其失败时直接报无可用源）
            if params.get("text_detection_model_name"):
                remaining = ensure_profile_models(
                    kwargs.get("model_profile", DEFAULT_PROFILE),
                    bool(kwargs.get("use_textline_orientation", False)),
                    self._progress,
                )
                if remaining:
                    logger.warning(
                        "镜像下载未完成，交由 PaddleX 继续尝试: %s", remaining
                    )

            # 重要：必须在 paddle 首次导入前设置环境
            self._set_mkldnn_env(params["enable_mkldnn"])
            os.environ["FLAGS_enable_pir_api"] = "0"
            # OMP 固定 1 线程：CPU 并行统一由 cpu_threads 控制，避免双线程池争抢
            apply_thread_env()

            from paddleocr import PaddleOCR

            logger.info(
                "OCR 运行配置: device=%s, enable_mkldnn=%s, cpu_threads=%s",
                params["device"],
                params["enable_mkldnn"],
                params["cpu_threads"],
            )

            try:
                self._ocr = self._create_ocr(PaddleOCR, params)
            except FileNotFoundError as e:
                if _is_corrupted_model_cache_error(e):
                    logger.warning("检测到模型缓存损坏，正在清理后重试: %s", e)
                    _clear_paddlex_model_cache()
                    self._ocr = self._create_ocr(PaddleOCR, params)
                else:
                    raise

            self._initialized = True
            self._error = None
            return True

        except ImportError as e:
            self._error = f"PaddleOCR未安装: {e}"
            return False
        except Exception as e:
            # 模型下载源瞬时不可用（网络波动）：等待后重试一次
            if is_download_source_error(e) and not kwargs.get("_download_retried"):
                logger.warning("模型下载源暂时不可用，3 秒后自动重试: %s", e)
                time.sleep(3)
                return self.initialize(**{**kwargs, "_download_retried": True})
            # OneDNN 在个别环境初始化失败：回退关闭 OneDNN 重建一次
            if kwargs.get("enable_mkldnn", False):
                logger.warning("OneDNN 初始化失败，自动回退关闭 OneDNN: %s", e)
                return self.initialize(**{**kwargs, "enable_mkldnn": False})
            logger.exception("OCR引擎初始化失败")  # 保留完整堆栈便于诊断
            self._error = f"OCR引擎初始化失败: {e}"
            return False

    @staticmethod
    def _set_mkldnn_env(enable: bool) -> None:
        """按配置设置 OneDNN 环境变量（必须在 paddle 导入前调用）"""
        if enable:
            os.environ.pop("FLAGS_use_mkldnn", None)
        else:
            os.environ["FLAGS_use_mkldnn"] = "0"

    @staticmethod
    def _create_ocr(PaddleOCR: Any, params: Dict[str, Any]) -> Any:
        """创建 PaddleOCR 实例，并同步 paddle 运行时开关"""
        ocr = PaddleOCR(**params)
        try:
            import paddle
            if hasattr(paddle, "set_flags"):
                paddle.set_flags(
                    {"FLAGS_use_mkldnn": bool(params.get("enable_mkldnn"))}
                )
        except Exception:
            pass
        return ocr

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
