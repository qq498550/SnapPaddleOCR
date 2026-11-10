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

# 处理线程积压判定阈值：超过说明处理线程已死亡或被长时间阻塞
_QUEUE_BACKLOG_LIMIT = 30
# 紧急重建限频：带线程泄漏的最后手段，24 小时内最多 2 次
_EMERGENCY_MAX_PER_DAY = 2
_EMERGENCY_COOLDOWN = 86400.0


# ── SendInput 结构（用于钩子活性探测：注入一对保留虚拟键 VK 0x07）──
class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort),
                ("wParamH", ctypes.c_ushort)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT),
                ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUT_UNION)]


_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_PROBE_VK = 0x07  # Windows 保留虚拟键（0x00~0x07 未定义），无字符/无绑定，对前台应用无影响


def _send_probe_keys() -> bool:
    """注入一对 VK 0x07 按下/抬起，用于探测低级键盘钩子是否仍在接收事件"""
    try:
        user32 = ctypes.windll.user32
        user32.SendInput.restype = ctypes.c_uint
        user32.SendInput.argtypes = [ctypes.c_uint,
                                     ctypes.POINTER(_INPUT), ctypes.c_int]

        def _one(up: bool) -> _INPUT:
            inp = _INPUT()
            inp.type = _INPUT_KEYBOARD
            inp.u.ki.wVk = _PROBE_VK
            inp.u.ki.dwFlags = _KEYEVENTF_KEYUP if up else 0
            return inp

        arr = (_INPUT * 2)(_one(False), _one(True))
        sent = user32.SendInput(2, arr, ctypes.sizeof(_INPUT))
        return sent == 2
    except Exception as e:
        logger.warning("钩子探测键注入失败: %s", e)
        return False


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

        # 全局事件计数器：钩子线程每收到一个键盘事件 +1，
        # 用于探测系统层钩子是否被 Windows 静默移除
        wk._snap_event_count = 0

        # ── 保护 1：事件预处理异常不中断事件流（钩子线程）──
        listener = getattr(kb, "_listener", None)
        if listener is not None:
            orig_pre = listener.pre_process_event

            def _counting_pre(event: Any, _orig: Callable = orig_pre) -> bool:
                wk._snap_event_count += 1
                try:
                    return _orig(event)
                except Exception:
                    logger.exception("热键事件预处理异常（已忽略该事件）")
                    return False

            listener.pre_process_event = _counting_pre

        # ── 保护 2：处理线程的回调异常不再杀死线程 ──
        # keyboard 原版 GenericListener.process 无任何 try 保护，
        # 业务回调中一次未捕获异常（如 Tk 窗口已销毁）即导致线程死亡，
        # 之后所有热键事件入队无人处理，表现为"必须重启才能恢复"。
        generic_cls = kb._generic.GenericListener

        def _patched_process(self: Any) -> None:
            while True:
                event = self.queue.get()
                try:
                    if self.pre_process_event(event):
                        self.invoke_handlers(event)
                except Exception:
                    logger.exception("热键回调异常（已忽略，处理线程继续运行）")
                try:
                    self.queue.task_done()
                except Exception:
                    pass

        generic_cls.process = _patched_process

        def _pump(callback: Callable[[Any], Any]) -> None:
            """监听线程主循环：常驻消息泵 + 按需重挂钩子（永不退出）"""
            installed = False
            install_retry = 0
            msg = msg_type()
            while True:
                try:
                    if not installed:
                        try:
                            wk.prepare_intercept(callback)  # 必须在安装线程派发
                            installed = True
                            install_retry = 0
                            logger.info("全局热键钩子已安装")
                        except Exception as e:
                            install_retry += 1
                            logger.error("安装键盘钩子失败（第 %d 次）: %s",
                                         install_retry, e)
                            # 退避重试，线程保持存活等待下一次尝试
                            time.sleep(min(1.0 + install_retry, 5.0))
                        continue
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
                            installed = True
                            logger.info("全局热键钩子已重新安装")
                        except Exception as e:
                            installed = False  # 回到重试逻辑
                            logger.error("重新安装热键钩子失败: %s", e)
                        finally:
                            _REHOOK_DONE.set()
                        continue
                    # 20ms 轮询：空闲时开销可忽略，且能及时响应重挂请求
                    time.sleep(0.02)
                except Exception:
                    # 泵线程绝不因任何异常退出（否则钩子随线程一起消失）
                    logger.exception("热键消息泵异常（已忽略，继续运行）")
                    time.sleep(0.1)

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
        self._emergency_log: list = []
        self._binding_provider: Optional[Callable[[], HotkeyBinding]] = None

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

    @staticmethod
    def _safe_callback(callback: Callable[[], None],
                       hotkey: str) -> Callable[[], None]:
        """包装用户回调：异常只记日志，绝不让异常冒泡到
        keyboard 的事件循环（原版处理线程会被异常杀死）"""

        def _wrapped() -> None:
            try:
                callback()
            except Exception:
                logger.exception("热键 %s 回调异常（不影响后续热键响应）", hotkey)

        return _wrapped

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
            self._keyboard.add_hotkey(hotkey, self._safe_callback(callback, hotkey))
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

        # 由监听线程重装系统钩子（补丁未生效时该步骤自动跳过）；
        # 超时自动重试一次，避免泵线程瞬时繁忙导致恢复失败
        wk = getattr(kb, "_winkeyboard", None)
        if wk is not None and getattr(wk, "_snap_patched", False):
            rehooked = False
            for attempt in range(2):
                _REHOOK_DONE.clear()
                _REHOOK_REQUEST.set()
                if _REHOOK_DONE.wait(timeout=3.0):
                    rehooked = True
                    break
                logger.warning("热键钩子重装超时（第 %d 次）", attempt + 1)
            if not rehooked:
                logger.error("热键钩子重装失败，将在下次健康检查时重试")
        else:
            time.sleep(0.2)

        reconnected = 0
        for hotkey, callback in saved.items():
            try:
                kb.add_hotkey(hotkey, self._safe_callback(callback, hotkey))
                self._callbacks[hotkey] = callback
                reconnected += 1
            except Exception as e:
                logger.warning("重连热键失败 %s: %s", hotkey, e)

        logger.info("全局热键已恢复 (%d/%d)", reconnected, len(saved))
        return reconnected > 0

    def probe_alive(self, timeout: float = 2.0) -> bool:
        """主动探测系统层键盘钩子是否存活

        Windows 会在回调超时、显示模式切换、UAC 弹窗、全屏应用等场景
        静默移除低级键盘钩子，且不提供任何查询接口。原实现（检查
        Python 层 _hooks 字典）永远返回 True，导致失效后永不自愈。

        探测原理：注入一对 Windows 保留虚拟键 VK 0x07（0x00~0x07 为
        未定义键，不产生字符、无系统语义、对前台应用无影响），钩子
        线程的事件计数器应随之增长；超时未增长即判定钩子已死亡。
        """
        kb = self._keyboard
        if not kb or not self._available:
            return False
        if not self._callbacks:
            return False
        wk = getattr(kb, "_winkeyboard", None)
        if wk is None or not getattr(wk, "_snap_patched", False):
            return bool(self._callbacks)  # 无补丁时退化为表检查
        base = getattr(wk, "_snap_event_count", 0)
        if not _send_probe_keys():
            return True  # 注入失败时保守认为存活（避免误报触发重建）
        deadline = time.time() + timeout
        while time.time() < deadline:
            if getattr(wk, "_snap_event_count", 0) > base:
                return True
            time.sleep(0.05)
        return False

    def ensure_alive(self, probe_timeout: float = 2.0) -> bool:
        """综合健康检查：处理线程活性 + 系统钩子活性，失效自动恢复

        供后台监控线程周期调用。返回 True 表示热键当前可用。
        """
        kb = self._keyboard
        if not kb or not self._available or not self._callbacks:
            return False

        # 1) 处理线程活性：事件队列持续积压说明线程已死亡或被卡死。
        #    （process/pre_process 已加异常保护，正常情况下不会发生；
        #    此为防御性兜底，恢复手段为限频的紧急重建。）
        listener = getattr(kb, "_listener", None)
        queue = getattr(listener, "queue", None)
        try:
            if hasattr(queue, "qsize"):
                backlog = queue.qsize()
            elif queue is not None:
                backlog = len(queue)
            else:
                backlog = 0
        except Exception:
            backlog = 0
        if backlog > _QUEUE_BACKLOG_LIMIT:
            logger.error("热键处理线程疑似停滞（队列积压 %d 个事件），"
                         "尝试紧急恢复", backlog)
            return self._emergency_rebuild()

        # 2) 系统钩子活性：探测失败则重挂钩子
        if not self.probe_alive(probe_timeout):
            logger.warning("探测到系统键盘钩子已失效（Windows 静默移除），"
                           "正在自动恢复...")
            return self.reconnect()
        return True

    def _emergency_rebuild(self) -> bool:
        """最后手段：完全重建 keyboard 模块（会遗留旧监听线程，限频使用）

        仅当处理线程死亡（正常情况下已被异常保护杜绝）时触发；
        每 24 小时最多 2 次，超出则退回普通重连并告警。
        """
        now = time.time()
        self._emergency_log = [t for t in self._emergency_log
                               if now - t < _EMERGENCY_COOLDOWN]
        if len(self._emergency_log) >= _EMERGENCY_MAX_PER_DAY:
            logger.error("紧急重建超出限频（24h 内 %d 次），跳过",
                         len(self._emergency_log))
            return self.reconnect()
        self._emergency_log.append(now)
        logger.warning("执行紧急重建（24h 内第 %d 次）", len(self._emergency_log))

        import sys
        kb = self._keyboard
        if kb:
            try:
                kb.unhook_all()
            except Exception:
                pass
        self._callbacks.clear()
        self._keyboard = None
        self._available = False
        time.sleep(0.3)
        for mod in list(sys.modules.keys()):
            if mod == "keyboard" or mod.startswith("keyboard."):
                del sys.modules[mod]
        if not self.init():
            return False
        reconnected = 0
        if self._binding_provider is not None:
            for hotkey, callback in self._binding_provider().items():
                if self.register(hotkey, callback):
                    reconnected += 1
        else:
            logger.warning("未设置绑定提供器，紧急重建后热键为空")
        logger.info("紧急重建完成，热键已恢复 %d 个", reconnected)
        return reconnected > 0

    def set_binding_provider(self, provider: Callable[[], HotkeyBinding]) -> None:
        """注册"当前配置的热键绑定"提供器，供紧急重建后恢复热键"""
        self._binding_provider = provider

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
