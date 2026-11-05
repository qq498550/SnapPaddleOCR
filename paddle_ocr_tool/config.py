# SnapPaddleOCR - 配置模块：管理用户配置的加载 / 读取 / 保存

import json
import logging
import os
from typing import Any, Dict, Optional

from .paths import CONFIG_PATH

logger = logging.getLogger("SnapPaddleOCR.Config")

CONFIG_FILE = CONFIG_PATH

DEFAULT_CONFIG: Dict[str, Any] = {
    # 通用设置
    "language": "ch",
    "ocr_version": "PP-OCRv6",

    # 设备与推理设置
    "device": "cpu",
    "enable_mkldnn": False,
    "cpu_threads": os.cpu_count() or 4,

    # 快捷键设置
    "screenshot_hotkey": "ctrl+shift+f",
    "clipboard_hotkey": "ctrl+shift+g",
    "quick_ocr_hotkey": "ctrl+shift+d",

    # OCR 参数
    "use_doc_orientation": False,
    "use_textline_orientation": False,
    "text_det_limit_side_len": 960,
    "text_det_limit_type": "max",
    "text_det_thresh": 0.3,
    "text_det_box_thresh": 0.6,
    "text_det_unclip_ratio": 1.5,
    "text_rec_score_thresh": 0.5,

    # 输出设置
    "auto_copy": True,
    "show_toast": True,
    "show_result_window": True,
    "result_layout": "raw",  # raw 逐段换行 / none 不换行

    # 界面设置
    "start_minimized": False,
    "autostart": False,
    "close_action": "minimize",  # minimize 最小化到托盘 / exit 退出
}


class Config:
    """配置管理器：JSON 持久化，支持单项读取与批量更新"""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self.config_path = config_path or CONFIG_FILE
        self._config: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """加载配置（文件缺失或损坏时回退到默认值）"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
            else:
                self._config = DEFAULT_CONFIG.copy()
                self.save()
        except Exception:
            self._config = DEFAULT_CONFIG.copy()
            self.save()

    def save(self) -> None:
        """保存配置到磁盘"""
        try:
            os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("配置保存失败: %s", e)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项（缺失时回退默认值）"""
        return self._config.get(key, DEFAULT_CONFIG.get(key, default))

    def set(self, key: str, value: Any) -> None:
        """设置单个配置项并立即持久化"""
        self._config[key] = value
        self.save()

    def update(self, items: Dict[str, Any]) -> None:
        """批量更新配置项，仅写盘一次（避免高频调用下的 I/O 放大）"""
        self._config.update(items)
        self.save()

    def get_all(self) -> Dict[str, Any]:
        """获取全部有效配置（以默认值补齐缺失项）"""
        result = {k: self._config.get(k, v) for k, v in DEFAULT_CONFIG.items()}
        return result


# 全局配置单例
config = Config()
