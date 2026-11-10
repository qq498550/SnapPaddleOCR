# PaddleOCR 截图文字识别工具
# 全局热键模块 - 注册系统和全局快捷键
#
# 后端架构（参考 Umi-OCR 的触发逻辑）：
#   主后端  RegisterHotKey + WM_HOTKEY 消息循环
#           热键由操作系统内核热键表管理，不占键盘钩子、不存在
#           "回调超时被系统移除"问题，锁屏/解锁/显示切换后自动恢复，
#           无需任何探测注入（注入保留虚拟键会在 LTSC 等精简系统上
#           触发 ms-gamingoverlay 弹窗）。
#   回退后端 keyboard 库低级键盘钩子（经消息泵补丁加固）
#           仅当某热键 RegisterHotKey 失败（被其它程序占用）或
#           键名无法解析时，按单个热键回退。

import ctypes
import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

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

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ── RegisterHotKey 后端常量 ──
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # Win7+：按住不放不重复触发
ERROR_HOTKEY_ALREADY_REGISTERED = 1409


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_void_p), ("lParam", ctypes.c_void_p),
                ("time", ctypes.c_ulong),
                ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]


# ── 热键字符串解析（"ctrl+alt+s" → MOD_CONTROL|MOD_ALT + VK 'S'）──
_MOD_ALIASES = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "ctl": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "windows": MOD_WIN, "super": MOD_WIN, "meta": MOD_WIN,
}
_VK_TABLE = {
    "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "space": 0x20, "spacebar": 0x20, "backspace": 0x08, "bksp": 0x08,
    "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdn": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "printscreen": 0x2C, "prtsc": 0x2C, "snapshot": 0x2C,
    "pause": 0x13, "break": 0x13, "capslock": 0x14, "numlock": 0x90,
    "scrolllock": 0x91,
    "apps": 0x5D, "menu": 0x5D,
    "add": 0x6B, "subtract": 0x6D, "multiply": 0x6A, "divide": 0x6F,
    "decimal": 0x6E,
    "mediaplaypause": 0xB3, "medianexttrack": 0xB0, "mediaprevtrack": 0xB1,
    "mediastop": 0xB2, "volumemute": 0xAD, "volumeup": 0xAF,
    "volumedown": 0xAE,
}
for _i in range(10):
    _VK_TABLE[f"numpad{_i}"] = 0x60 + _i


def _parse_hotkey(hotkey: str) -> Optional[Tuple[int, int]]:
    """解析热键字符串为 (modifiers, virtual_key)；无法解析返回 None"""
    mods = 0
    vk = None
    for part in hotkey.lower().replace(" ", "").split("+"):
        if not part:
            continue
        if part in _MOD_ALIASES:
            mods |= _MOD_ALIASES[part]
        elif part in _VK_TABLE:
            vk = _VK_TABLE[part]
        elif part.startswith("f") and part[1:].isdigit() \
                and 1 <= int(part[1:]) <= 24:
            vk = 0x6F + int(part[1:])  # F1=0x70
        elif len(part) == 1:
            ch = part.upper()
            if "A" <= ch <= "Z" or "0" <= ch <= "9":
                vk = ord(ch)
            else:
                # 标点符号：经 VkKeyScanW 转换（忽略其 shift 状态位）
                _user32.VkKeyScanW.restype = ctypes.c_short
                _user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
                scanned = _user32.VkKeyScanW(part)
                if scanned == -1:
                    return None
                vk = scanned & 0xFF
        else:
            return None
    if vk is None:
        return None
    return (mods | MOD_NOREPEAT, vk)


class _RegisterHotkeyBackend:
    """RegisterHotKey 主后端：专用守护线程 + WM_HOTKEY 消息循环

    WM_HOTKEY 投递到调用 RegisterHotKey 的线程，因此注册/注销命令
    经命令队列在热键线程内执行；回调也由该线程顺序调用（要求回调
    轻量、不阻塞，本项目的 OCR 回调均为非阻塞任务派发）。
    """

    def __init__(self) -> None:
        self._cmdq: "queue.Queue[tuple]" = queue.Queue()
        self._id_to_cb: Dict[int, Tuple[str, Callable[[], None]]] = {}
        self._name_to_id: Dict[str, int] = {}
        self._next_id = 1
        self._stopping = False
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping = False
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="hotkey-register")
        self._thread.start()
        self._ready.wait(timeout=3.0)

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        user32 = _user32
        user32.RegisterHotKey.restype = ctypes.c_int
        user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_uint, ctypes.c_uint]
        user32.UnregisterHotKey.restype = ctypes.c_int
        user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.PeekMessageW.restype = ctypes.c_int
        user32.PeekMessageW.argtypes = [ctypes.POINTER(_MSG), ctypes.c_void_p,
                                        ctypes.c_uint, ctypes.c_uint,
                                        ctypes.c_uint]
        _kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
        self._thread_id = _kernel32.GetCurrentThreadId()
        self._ready.set()

        msg = _MSG()
        while not self._stopping:
            try:
                # 1) 执行注册/注销命令（RegisterHotKey 必须由接收
                #    WM_HOTKEY 的线程调用）
                while True:
                    try:
                        cmd = self._cmdq.get_nowait()
                    except queue.Empty:
                        break
                    op = cmd[0]
                    if op == "reg":
                        _, hotkey, mod, vk, callback, ev, box = cmd
                        # 同名重注册：先注销旧 id
                        old_id = self._name_to_id.get(hotkey)
                        if old_id is not None:
                            user32.UnregisterHotKey(None, old_id)
                            self._id_to_cb.pop(old_id, None)
                        new_id = self._next_id
                        self._next_id += 1
                        if user32.RegisterHotKey(None, new_id, mod, vk):
                            self._name_to_id[hotkey] = new_id
                            self._id_to_cb[new_id] = (hotkey, callback)
                            box["ok"] = True
                        else:
                            err = ctypes.get_last_error()
                            reason = ("已被其它程序占用" if
                                      err == ERROR_HOTKEY_ALREADY_REGISTERED
                                      else f"错误码 {err}")
                            logger.warning("RegisterHotKey 失败 %s: %s",
                                           hotkey, reason)
                            box["ok"] = False
                            box["err"] = reason
                        ev.set()
                    elif op == "unreg":
                        _, hotkey, ev, box = cmd
                        hid = self._name_to_id.pop(hotkey, None)
                        if hid is not None:
                            user32.UnregisterHotKey(None, hid)
                            self._id_to_cb.pop(hid, None)
                        box["ok"] = True
                        ev.set()
                    elif op == "quit":
                        self._stopping = True
                        break

                # 2) 消息循环（PeekMessage 轮询，风格与消息泵补丁一致）
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0,
                                          _PM_REMOVE):
                    if msg.message == WM_HOTKEY:
                        info = self._id_to_cb.get(msg.wParam or 0)
                        if info is not None:
                            try:
                                info[1]()
                            except Exception:
                                logger.exception("热键 %s 回调异常",
                                                 info[0])
                    elif msg.message == WM_QUIT:
                        self._stopping = True
                        break
                    else:
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))

                time.sleep(0.02)
            except Exception:
                # 热键线程绝不因异常退出
                logger.exception("热键线程异常（已忽略，继续运行）")
                time.sleep(0.1)

        # 退出前注销全部系统热键
        for hid in list(self._name_to_id.values()):
            try:
                user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
        self._name_to_id.clear()
        self._id_to_cb.clear()

    def register(self, hotkey: str,
                 callback: Callable[[], None]) -> Tuple[bool, str]:
        parsed = _parse_hotkey(hotkey)
        if parsed is None:
            return False, "无法识别的键名"
        mod, vk = parsed
        ev = threading.Event()
        box: Dict[str, Any] = {}
        self._cmdq.put(("reg", hotkey, mod, vk, callback, ev, box))
        if not ev.wait(timeout=2.0):
            return False, "热键线程无响应"
        return box.get("ok", False), box.get("err", "")

    def unregister(self, hotkey: str) -> None:
        if hotkey not in self._name_to_id:
            return
        ev = threading.Event()
        box: Dict[str, Any] = {}
        self._cmdq.put(("unreg", hotkey, ev, box))
        ev.wait(timeout=2.0)

    def close(self) -> None:
        ev = threading.Event()
        self._cmdq.put(("quit", ev))
        ev.wait(timeout=2.0)


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

        # ── 保护 1：事件预处理异常不中断事件流（钩子线程）──
        listener = getattr(kb, "_listener", None)
        if listener is not None:
            orig_pre = listener.pre_process_event

            def _guarded_pre(event: Any, _orig: Callable = orig_pre) -> bool:
                try:
                    return _orig(event)
                except Exception:
                    logger.exception("热键事件预处理异常（已忽略该事件）")
                    return False

            listener.pre_process_event = _guarded_pre

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
    """全局热键管理器（RegisterHotKey 主后端 + keyboard 钩子回退）"""

    # 两次重连的最小间隔（秒）：防止异常场景下高频重建
    MIN_RECONNECT_INTERVAL = 20.0

    def __init__(self) -> None:
        self._callbacks: HotkeyBinding = {}  # hotkey -> 原始回调
        self._backend_map: Dict[str, str] = {}  # hotkey -> "reg"/"hook"
        self._keyboard = None
        self._hook_available = False
        self._reg: Optional[_RegisterHotkeyBackend] = None
        self._available = False
        self._last_reconnect = 0.0
        self._restart_log: list = []
        self._binding_provider: Optional[Callable[[], HotkeyBinding]] = None

    def init(self) -> bool:
        """初始化热键系统

        主后端 RegisterHotKey 不依赖任何第三方库；
        keyboard 库仅作为回退路径按需加载（同时修补其消息泵缺陷）。
        """
        self._reg = _RegisterHotkeyBackend()
        self._reg.start()
        if not self._reg.alive:
            logger.error("RegisterHotKey 热键线程启动失败")
            return False
        try:
            import keyboard
            self._keyboard = keyboard
            _patch_keyboard_pump(keyboard)
            self._hook_available = True
        except ImportError:
            logger.warning("keyboard 模块未安装，占用冲突的热键将无法回退")
        self._available = True
        return True

    @staticmethod
    def _safe_callback(callback: Callable[[], None],
                       hotkey: str) -> Callable[[], None]:
        """包装用户回调：异常只记日志，绝不让异常冒泡到热键线程
        （keyboard 原版处理线程会被异常杀死）"""

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
        """注册全局热键（优先 RegisterHotKey，失败回退键盘钩子）

        Args:
            hotkey: 快捷键字符串，如 "ctrl+shift+f"
            callback: 回调函数（需轻量、非阻塞）
        """
        if not self._available:
            logger.warning(f"热键不可用，无法注册: {hotkey}")
            return False
        if hotkey in self._callbacks:
            self.unregister(hotkey)

        safe = self._safe_callback(callback, hotkey)

        # 主后端：系统热键表（不占钩子、不会被系统移除、免探测）
        ok, reason = self._reg.register(hotkey, safe)
        if ok:
            self._callbacks[hotkey] = callback
            self._backend_map[hotkey] = "reg"
            logger.info(f"已注册热键（RegisterHotKey）: {hotkey}")
            return True

        # 回退后端：keyboard 低级键盘钩子
        if self._hook_available:
            try:
                # 不使用 suppress=True：可能丢失修饰键抬起事件，造成
                # 全局键盘输入混乱。
                self._keyboard.add_hotkey(hotkey, safe)
                self._callbacks[hotkey] = callback
                self._backend_map[hotkey] = "hook"
                logger.info(f"已注册热键（钩子回退，RegisterHotKey {reason}）: "
                            f"{hotkey}")
                return True
            except Exception as e:
                logger.error(f"注册热键失败 {hotkey}: {e}")
                return False

        logger.error(f"注册热键失败 {hotkey}: {reason}，且回退后端不可用")
        return False

    def unregister(self, hotkey: str) -> None:
        """取消注册热键"""
        if hotkey not in self._callbacks:
            return
        backend = self._backend_map.pop(hotkey, None)
        try:
            if backend == "reg" and self._reg:
                self._reg.unregister(hotkey)
            elif backend == "hook" and self._keyboard:
                self._keyboard.remove_hotkey(hotkey)
        except Exception as e:
            logger.error(f"取消热键失败 {hotkey}: {e}")
        self._callbacks.pop(hotkey, None)

    def unregister_all(self) -> None:
        """取消所有热键"""
        for hotkey in list(self._callbacks.keys()):
            self.unregister(hotkey)

    @property
    def has_callbacks(self) -> bool:
        """当前是否有已注册的热键回调"""
        return bool(self._callbacks)

    @property
    def backend_summary(self) -> str:
        """当前热键后端分布（诊断用），如 'reg=3 hook=0'"""
        reg = sum(1 for v in self._backend_map.values() if v == "reg")
        hook = len(self._backend_map) - reg
        return f"reg={reg} hook={hook}"

    def reconnect(self) -> bool:
        """恢复失效的全局热键（仅钩子回退的键需要；RegisterHotKey
        键由系统管理，锁屏/解锁/显示切换后自动恢复，无需重连）"""
        hook_keys = [k for k, v in self._backend_map.items() if v == "hook"]
        if not hook_keys:
            return True
        kb = self._keyboard
        if not kb or not self._hook_available:
            return False

        now = time.time()
        if now - self._last_reconnect < self.MIN_RECONNECT_INTERVAL:
            logger.info("热键重连过于频繁，已跳过本次")
            return False
        self._last_reconnect = now

        saved = {k: self._callbacks[k] for k in hook_keys}
        for k in hook_keys:
            self._backend_map.pop(k, None)
            self._callbacks.pop(k, None)
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
                self._backend_map[hotkey] = "hook"
                reconnected += 1
            except Exception as e:
                logger.warning("重连热键失败 %s: %s", hotkey, e)

        logger.info("钩子回退热键已恢复 (%d/%d)", reconnected, len(saved))
        return reconnected > 0

    def ensure_alive(self) -> bool:
        """综合健康检查，失效自动恢复

        - RegisterHotKey 后端：检查热键线程是否存活（系统热键表本身
          由内核管理，不会失效），线程死亡则限频重启并重新注册
        - 钩子回退键：检查事件队列是否积压（处理线程停滞）
        """
        if not self._available or not self._callbacks:
            return False

        # 1) RegisterHotKey 线程活性
        if self._reg is not None and not self._reg.alive:
            now = time.time()
            self._restart_log = [t for t in self._restart_log
                                 if now - t < _EMERGENCY_COOLDOWN]
            if len(self._restart_log) >= _EMERGENCY_MAX_PER_DAY:
                logger.error("热键线程重启超出限频（24h 内 %d 次），跳过",
                             len(self._restart_log))
                return False
            self._restart_log.append(now)
            logger.warning("RegisterHotKey 热键线程已停止，执行重启恢复")
            reg_keys = {k: v for k, v in self._callbacks.items()
                        if self._backend_map.get(k) == "reg"}
            self._reg.close()
            self._reg = _RegisterHotkeyBackend()
            self._reg.start()
            restored = 0
            for hotkey, callback in reg_keys.items():
                if self.register(hotkey, callback):
                    restored += 1
            logger.info("热键线程重启完成，恢复 %d/%d 个热键",
                        restored, len(reg_keys))
            return self._reg.alive

        # 2) 钩子回退键：处理线程队列积压检测（无注入探测——注入保留
        #    虚拟键会在 LTSC 等精简系统上触发 ms-gamingoverlay 弹窗）
        if self._hook_available:
            kb = self._keyboard
            listener = getattr(kb, "_listener", None)
            q = getattr(listener, "queue", None)
            try:
                backlog = q.qsize() if hasattr(q, "qsize") else \
                    (len(q) if q is not None else 0)
            except Exception:
                backlog = 0
            if backlog > _QUEUE_BACKLOG_LIMIT:
                logger.error("热键处理线程疑似停滞（队列积压 %d 个事件），"
                             "尝试紧急恢复", backlog)
                return self._emergency_rebuild()
        return True

    def _emergency_rebuild(self) -> bool:
        """最后手段：完全重建 keyboard 模块（会遗留旧监听线程，限频使用）

        仅当处理线程死亡（正常情况下已被异常保护杜绝）时触发；
        每 24 小时最多 2 次，超出则退回普通重连并告警。
        """
        now = time.time()
        self._restart_log = [t for t in self._restart_log
                             if now - t < _EMERGENCY_COOLDOWN]
        if len(self._restart_log) >= _EMERGENCY_MAX_PER_DAY:
            logger.error("紧急重建超出限频（24h 内 %d 次），跳过",
                         len(self._restart_log))
            return self.reconnect()
        self._restart_log.append(now)
        logger.warning("执行紧急重建（24h 内第 %d 次）", len(self._restart_log))

        import sys
        kb = self._keyboard
        if kb:
            try:
                kb.unhook_all()
            except Exception:
                pass
        for hotkey in [k for k, v in self._backend_map.items() if v == "hook"]:
            self._backend_map.pop(hotkey, None)
            self._callbacks.pop(hotkey, None)
        self._keyboard = None
        self._hook_available = False
        time.sleep(0.3)
        for mod in list(sys.modules.keys()):
            if mod == "keyboard" or mod.startswith("keyboard."):
                del sys.modules[mod]
        try:
            import keyboard
            self._keyboard = keyboard
            _patch_keyboard_pump(keyboard)
            self._hook_available = True
        except ImportError:
            logger.error("紧急重建失败：keyboard 模块无法重新导入")
            return False
        reconnected = 0
        if self._binding_provider is not None:
            for hotkey, callback in self._binding_provider().items():
                if self._backend_map.get(hotkey) == "hook" \
                        and self.register(hotkey, callback):
                    reconnected += 1
        else:
            logger.warning("未设置绑定提供器，紧急重建后热键为空")
        logger.info("紧急重建完成，热键已恢复 %d 个", reconnected)
        return reconnected > 0

    def set_binding_provider(self, provider: Callable[[], HotkeyBinding]) -> None:
        """注册"当前配置的热键绑定"提供器，供紧急重建后恢复热键"""
        self._binding_provider = provider

    def is_alive(self) -> bool:
        """热键系统是否可用（RegisterHotKey 线程存活 + 有已注册热键）"""
        if not self._available or not self._callbacks:
            return False
        if self._reg is not None:
            return self._reg.alive
        return bool(self._keyboard)

    def close(self) -> None:
        """关闭热键管理器（守护线程随进程退出）"""
        self.unregister_all()
        if self._reg is not None:
            try:
                self._reg.close()
            except Exception:
                pass
            self._reg = None
        if self._keyboard:
            try:
                self._keyboard.unhook_all()
            except Exception:
                pass
            self._keyboard = None
        self._available = False


# 全局热键管理器
hotkey_manager = HotkeyManager()
