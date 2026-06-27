# PaddleOCR 截图文字识别工具
# 配置模块 - 管理用户配置和设置

import json
import os

from .paths import CONFIG_PATH

CONFIG_FILE = CONFIG_PATH

DEFAULT_CONFIG = {
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
    
    # OCR参数
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
    "auto_paste": False,
    "show_result_window": True,
    "result_layout": "raw",  # raw 逐段换行 / none 不换行
    "result_format": "text",  # text, json
    "save_to_file": False,
    "save_directory": "",
    
    # 界面设置
    "start_minimized": False,
    "autostart": False,
    "close_action": "minimize",  # minimize 最小化到托盘 / exit 退出
    "language_ui": "zh_CN",
}


class Config:
    """配置管理器"""
    
    def __init__(self, config_path=None):
        self.config_path = config_path or CONFIG_FILE
        self._config = {}
        self.load()
    
    def load(self):
        """加载配置"""
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
    
    def save(self):
        """保存配置"""
        try:
            os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to save config: {e}")
    
    def get(self, key, default=None):
        """获取配置项"""
        return self._config.get(key, DEFAULT_CONFIG.get(key, default))
    
    def set(self, key, value):
        """设置配置项"""
        self._config[key] = value
        self.save()
    
    def get_all(self):
        """获取所有配置"""
        result = {}
        for k, v in DEFAULT_CONFIG.items():
            result[k] = self._config.get(k, v)
        return result


config = Config()
