# PaddleOCR 截图文字识别工具
# 全局热键模块 - 注册系统和全局快捷键

import threading
import time
import logging

logger = logging.getLogger("PaddleOCR_Tool.Hotkey")


class HotkeyManager:
    """全局热键管理器"""
    
    def __init__(self):
        self._callbacks = {}
        self._running = False
        self._thread = None
        self._keyboard = None
        self._available = False
    
    def init(self):
        """初始化热键系统"""
        try:
            import keyboard
            self._keyboard = keyboard
            self._available = True
            return True
        except ImportError:
            logger.warning("keyboard模块未安装，全局热键不可用")
            self._available = False
            return False
    
    def register(self, hotkey, callback):
        """注册全局热键
        
        Args:
            hotkey: 快捷键字符串，如 "ctrl+shift+f"
            callback: 回调函数
        """
        if not self._available:
            logger.warning(f"热键不可用，无法注册: {hotkey}")
            return False
        
        try:
            self._keyboard.add_hotkey(hotkey, callback)
            self._callbacks[hotkey] = callback
            logger.info(f"已注册热键: {hotkey}")
            return True
        except Exception as e:
            logger.error(f"注册热键失败 {hotkey}: {e}")
            return False
    
    def unregister(self, hotkey):
        """取消注册热键"""
        if not self._available or hotkey not in self._callbacks:
            return
        
        try:
            self._keyboard.remove_hotkey(hotkey)
            del self._callbacks[hotkey]
        except Exception as e:
            logger.error(f"取消热键失败 {hotkey}: {e}")
    
    def unregister_all(self):
        """取消所有热键"""
        for hotkey in list(self._callbacks.keys()):
            self.unregister(hotkey)
    
    def close(self):
        """关闭热键管理器"""
        self.unregister_all()
        if self._keyboard:
            try:
                self._keyboard.unhook_all()
            except:
                pass
            self._keyboard = None
        self._available = False


# 全局热键管理器
hotkey_manager = HotkeyManager()
