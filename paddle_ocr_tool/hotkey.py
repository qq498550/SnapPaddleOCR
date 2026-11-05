# PaddleOCR 截图文字识别工具
# 全局热键模块 - 注册系统和全局快捷键

import threading
import time
import logging
from typing import Callable, Dict

logger = logging.getLogger("SnapPaddleOCR.Hotkey")

HotkeyBinding = Dict[str, Callable[[], None]]


class HotkeyManager:
    """全局热键管理器"""

    def __init__(self) -> None:
        self._callbacks: HotkeyBinding = {}
        self._running = False
        self._thread = None
        self._keyboard = None
        self._available = False

    def init(self) -> bool:
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

    def register_all(self, bindings: HotkeyBinding) -> None:
        """批量注册全局热键

        Args:
            bindings: {热键字符串: 回调} 映射，如
                {"ctrl+shift+f": on_screenshot, ...}
        """
        for hotkey, callback in bindings.items():
            self.register(hotkey, callback)

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        """注册全局热键

        Args:
            hotkey: 快捷键字符串，如 "ctrl+shift+f"
            callback: 回调函数
        """
        if not self._available:
            logger.warning(f"热键不可用，无法注册: {hotkey}")
            return False
        
        try:
            # 不使用 suppress=True：虽然可以阻止组合键传递给前台应用，
            # 但在 Windows 低级键盘钩子中，suppress 可能因异常导致修饰键
            # （Shift/Ctrl/Alt）的"抬起"事件丢失，使系统认为修饰键一直
            # 处于按下状态，造成全局键盘输入混乱。
            self._keyboard.add_hotkey(hotkey, callback)
            self._callbacks[hotkey] = callback
            logger.info(f"已注册热键: {hotkey}")
            return True
        except Exception as e:
            logger.error(f"注册热键失败 {hotkey}: {e}")
            return False
    
    def unregister(self, hotkey: str) -> None:
        """取消注册热键"""
        if not self._available or hotkey not in self._callbacks:
            return
        
        try:
            self._keyboard.remove_hotkey(hotkey)
            del self._callbacks[hotkey]
        except Exception as e:
            logger.error(f"取消热键失败 {hotkey}: {e}")
    
    def unregister_all(self) -> None:
        """取消所有热键"""
        for hotkey in list(self._callbacks.keys()):
            self.unregister(hotkey)

    @property
    def has_callbacks(self) -> bool:
        """当前是否有已注册的热键回调"""
        return bool(self._callbacks)
    
    def reconnect(self) -> bool:
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

    def is_alive(self) -> bool:
        """检测键盘钩子是否仍然存活

        Windows 可能在以下场景静默移除低级键盘钩子：
        - 显示模式切换（全屏应用、分辨率变更）
        - UAC 提权弹窗
        - 某些安全软件/游戏的反作弊系统
        - 钩子回调超时

        通过检查 keyboard 内部钩子状态来判断是否需要重连。
        """
        if not self._available or not self._keyboard:
            return False
        try:
            # keyboard 库内部的 _hooks 字典记录了活跃钩子
            # 如果没有任何钩子，说明已被系统移除
            hooks = getattr(self._keyboard, '_hooks', None)
            if hooks is None:
                return bool(self._callbacks)
            # 有钩子记录就算存活
            return bool(hooks)
        except Exception:
            return bool(self._callbacks)

    def close(self) -> None:
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
