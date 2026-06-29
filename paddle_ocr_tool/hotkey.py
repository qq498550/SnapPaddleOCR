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
    
    def reconnect(self):
        """完全重启热键监听器（用于锁屏/休眠恢复后自动修复）

        系统锁屏后 Windows 会从底层撤销低级键盘钩子，且 keyboard
        库内部的 ctypes 钩子句柄、监听器线程状态都已损坏。
        仅 unhook_all()+add_hotkey() 无法恢复，必须强制重置模块。
        """
        if not self._callbacks:
            return False
        try:
            # 1. 保存回调映射
            saved = dict(self._callbacks)
            self._callbacks.clear()

            # 2. 完全关闭现有钩子和监听器
            if self._keyboard:
                try:
                    self._keyboard.unhook_all()
                except Exception:
                    pass
                self._keyboard = None
            self._available = False

            # 3. 等待系统完全恢复
            time.sleep(0.5)

            # 4. 强制重新导入 keyboard 模块（清空 sys.modules 缓存）
            #    确保全新的 Windows 钩子句柄和监听器线程
            import sys
            for mod in list(sys.modules.keys()):
                if mod == 'keyboard' or mod.startswith('keyboard.'):
                    del sys.modules[mod]

            import keyboard
            self._keyboard = keyboard
            self._available = True

            # 5. 重新注册所有热键
            reconnected = 0
            for hotkey, callback in saved.items():
                try:
                    self._keyboard.add_hotkey(hotkey, callback)
                    self._callbacks[hotkey] = callback
                    reconnected += 1
                except Exception as e:
                    logger.warning(f"重连热键失败 {hotkey}: {e}")

            logger.info("全局热键监听器已完全重启 (%d/%d)", reconnected, len(saved))
            return reconnected > 0
        except Exception as e:
            logger.error(f"热键重连失败: {e}")
            return False

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
