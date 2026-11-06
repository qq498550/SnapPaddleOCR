"""打包产物自检：验证冻结环境下 OCR 推理链路可用

由构建脚本以 `SnapPaddleOCR.exe --selftest` 调用，不启动界面/托盘/热键。
结果同时写入可执行文件同目录的 _selftest.log（窗口模式无控制台输出）。
"""
import os
import sys
import time
import traceback
from pathlib import Path


def _log_file() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    return base / "_selftest.log"


def run() -> int:
    """执行自检，返回进程退出码（0 成功）"""
    import logging

    # 详细日志（诊断下载失败原因）：窗口模式无 stderr，重定向到文件
    debug_log = _log_file().with_name("_selftest_debug.log")
    try:
        _debug_fp = open(debug_log, "w", encoding="utf-8", buffering=1)
        sys.stdout = _debug_fp
        sys.stderr = _debug_fp
        logging.basicConfig(
            stream=_debug_fp, level=logging.DEBUG, force=True,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    except Exception:
        _debug_fp = None

    lines = []
    ok = False
    eng = None
    try:
        # 网络栈可用性（模型下载依赖）
        net = []
        for mod in ("requests", "urllib3", "huggingface_hub", "filelock", "certifi"):
            try:
                __import__(mod)
                net.append(f"{mod}=ok")
            except Exception as exc:
                net.append(f"{mod}=FAIL({exc})")
        lines.append("net: " + " ".join(net))
    except Exception:
        pass

    try:
        from . import __version__
        from .config import config
        from .env_config import setup_paddle_env
        from .ocr_engine import (
            OCREngine,
            profile_label,
            sync_bundled_models,
        )
        from .paths import CACHE_DIR

        setup_paddle_env()
        lines.append(f"version={__version__}")
        lines.append(f"frozen={getattr(sys, 'frozen', False)}")
        lines.append(f"cache_dir={CACHE_DIR}")
        lines.append(f"profile={profile_label(config.get('model_profile'))}")
        missing = sync_bundled_models(
            config.get("model_profile", "lite"),
            bool(config.get("use_textline_orientation", False)),
        )
        lines.append(f"models_missing={missing}")

        import numpy as np
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (640, 240), "white")
        draw = ImageDraw.Draw(img)
        draw.text((24, 48), "SnapPaddleOCR selftest 2026 AB", fill="black")
        draw.text((24, 128), "Second line 0123456789", fill="black")

        eng = OCREngine()
        t0 = time.perf_counter()
        ok = eng.initialize(**config.get_all())
        init_s = time.perf_counter() - t0
        lines.append(f"init ok={ok} {init_s:.1f}s err={eng.error_message}")
        if ok:
            t0 = time.perf_counter()
            res = eng.recognize(img)
            wall = time.perf_counter() - t0
            texts = [item["text"] for item in res["data"]]
            lines.append(f"ocr {wall:.2f}s items={len(texts)} texts={texts}")
            ok = res["code"] == 100 and len(texts) >= 1
    except Exception:
        lines.append(traceback.format_exc())
        ok = False
    finally:
        if eng is not None:
            try:
                eng.close()
            except Exception:
                pass

    lines.append("SELFTEST OK" if ok else "SELFTEST FAIL")
    text = "\n".join(lines)
    try:
        _log_file().write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        print(text)
    except Exception:
        pass
    return 0 if ok else 1
