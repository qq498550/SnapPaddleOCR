# PaddleOCR 截图文字识别工具
# 全局热键模块 - 注册系统和全局快捷键

import ctypes
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("SnapPaddleOCR.Hotkey")

HotkeyBinding = Dict[str, Callable[[], None]]

# ── 钩子重装信号（由监听线程自行处理，避免跨线程装卸引发原生崩溃）──
_REHOOK_REQUEST = threading.Event()
_REHOOK_DONE = threading.Event()
_PM_REMOVE = 0x0001


def _patch_keyboard_pump(kb: Any) -> bool:
    """替换 keyboard 库的消息泵，修复两个致命缺陷

    缺陷 1（内存泄漏）：keyboard 的 listen() 用 `while not GetMessage(...)`
    反逻辑循环，收到 WM_QUIT（返回 0）反而继续循环，监听线程无法退出；
    而 processing 线程是 `while True: queue.get()`，同样永不退出。
    每重建一次模块即泄漏 2 个永久线程 + 钩子/线程句柄（实测每次约 2.4MB）。

    缺陷 2（无法重挂钩子）：系统锁屏/UAC/显示切换后低级键盘钩子失效时，
    原实现只能删除 sys.modules 中的 keyboard 重导入，但
    keyboard.unhook_all() 从不调用 UnhookWindowsHookEx，旧钩子仍驻留，
    且新引入的线程继续累积。

    修复后：监听线程常驻且消息泵循环可控，需要恢复热键时由该线程
    （低级钩子必须由安装它的线程卸载/安装）自行卸载并重装钩子，
    不再新建线程、不再重建模块，从根上消除泄漏。
    """
    wk = getattr(kb, "_winkeyboard", None)
    if wk is None or getattr(wk, "_snap_patched", False):
        return False
    try:
        msg_type = wk.MSG
        user32 = ctypes.windll.user32
        peek = user32.PeekMessageW
        peek.argtypes = [ctypes.POINTER(msg_type), ctypes.c_void_p,
                         ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        peek.restype = ctypes.c_int

        # 记录钩子句柄（keyboard 库将其保存在局部变量中，外部无法获取）
        orig_set_hook = wk.SetWindowsHookEx

        def _set_hook(*args: Any, _orig: Callable = orig_set_hook) -> Any:
            handle = _orig(*args)
            wk._snap_hook_handle = handle
            return handle

        wk.SetWindowsHookEx = _set_hook

        def _pump(callback: Callable[[Any], Any]) -> None:
            """监听线程主循环：常驻消息泵 + 按需重挂钩子"""
            wk.prepare_intercept(callback)  # 低级钩子必须在安装线程派发
            msg = msg_type()
            while True:
                # 非阻塞取消息（PeekMessage 同样会派发低级钩子回调）
                if peek(ctypes.byref(msg), None, 0, 0, _PM_REMOVE):
                    wk.TranslateMessage(ctypes.byref(msg))
                    wk.DispatchMessage(ctypes.byref(msg))
                    continue
                if _REHOOK_REQUEST.is_set():
                    _REHOOK_REQUEST.clear()
                    old = getattr(wk, "_snap_hook_handle", None)
                    if old:
                        try:
                            wk.UnhookWindowsHookEx(old)
                        except Exception:
                            pass
                    try:
                        wk.prepare_intercept(callback)
                        logger.info("全局热键钩子已重新安装")
                    except Exception as e:
                        logger.error("重新安装热键钩子失败: %s", e)
                    finally:
                        _REHOOK_DONE.set()
                    continue
                # 20ms 轮询：空闲时开销可忽略，且能及时响应重挂请求
                time.sleep(0.02)

        wk.listen = _pump
        wk._snap_patched = True
        return True
    except Exception as e:
        logger.warning("热键消息泵补丁失败（使用兼容模式）: %s", e)
        return False


class HotkeyManager:
    """全局热键管理器"""

    # 两次重连的最小间隔（秒）：防止异常场景下高频重建
    MIN_RECONNECT_INTERVAL = 20.0

    def __init__(self) -> None:
        self._callbacks: HotkeyBinding = {}
        self._running = False
        self._thread = None
        self._keyboard = None
        self._available = False
        self._last_reconnect = 0.0

    def init(self) -> bool:
        """初始化热键系统（同时修补 keyboard 库的消息泵缺陷）"""
        try:
            import keyboard
            self._keyboard = keyboard
            _patch_keyboard_pump(keyboard)
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
            # 先移除同名热键，避免重复注册导致回调被触发多次
            if hotkey in self._callbacks:
                try:
                    self._keyboard.remove_hotkey(hotkey)
                except Exception:
                    pass
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
        """恢复失效的全局热键（锁屏/休眠/UAC/显示切换后自动修复）

        关键修复：不再销毁并重建 keyboard 模块。原实现每次重连都会
        遗留 2 个永不退出的监听线程与底层钩子（内存/句柄持续增长，
        长时间开机运行可从数百 MB 涨到数 GB），且 keyboard.unhook_all()
        从不真正调用 UnhookWindowsHookEx。

        现在改为：由常驻监听线程自行卸载并重新安装低级键盘钩子
        （低级钩子只能在其安装线程内装卸），再重新登记回调。
        线程数与句柄数保持不变，可无限次重连。
        """
        if not self._callbacks:
            return False
        kb = self._keyboard
        if not kb or not self._available:
            return False

        now = time.time()
        if now - self._last_reconnect < self.MIN_RECONNECT_INTERVAL:
            logger.info("热键重连过于频繁，已跳过本次")
            return False
        self._last_reconnect = now

        saved = dict(self._callbacks)
        self._callbacks.clear()
        try:
            kb.unhook_all()  # 清空 Python 侧回调表（不触碰系统钩子）
        except Exception:
            pass

        # 由监听线程重装系统钩子（补丁未生效时该步骤自动跳过）
        wk = getattr(kb, "_winkeyboard", None)
        if wk is not None and getattr(wk, "_snap_patched", False):
            _REHOOK_DONE.clear()
            _REHOOK_REQUEST.set()
            if not _REHOOK_DONE.wait(timeout=3.0):
                logger.warning("热键钩子重装超时")
        else:
            time.sleep(0.2)

        reconnected = 0
        for hotkey, callback in saved.items():
            try:
                kb.add_hotkey(hotkey, callback)  # 监听线程已存在，不会新建
                self._callbacks[hotkey] = callback
                reconnected += 1
            except Exception as e:
                logger.warning("重连热键失败 %s: %s", hotkey, e)

        logger.info("全局热键已恢复 (%d/%d)", reconnected, len(saved))
        return reconnected > 0

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
        """关闭热键管理器（监听线程为守护线程，随进程退出）"""
        self.unregister_all()
        if self._keyboard:
            try:
                self._keyboard.unhook_all()
            except Exception:
                pass
            self._keyboard = None
        self._available = False


# 全局热键管理器
hotkey_manager = HotkeyManager()
