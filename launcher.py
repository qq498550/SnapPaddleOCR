"""SnapPaddleOCR · 启动器 - 自动检测并安装缺失依赖"""

import sys
import subprocess
import importlib
import os
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── 依赖列表 ──
# (import_name, pip_name, required)
DEPENDENCIES = [
    ("PIL",          "Pillow",       True),
    ("paddle",       "paddlepaddle", True),
    ("paddleocr",    "paddleocr",    True),
    ("keyboard",     "keyboard",     False),
    ("pystray",      "pystray",      False),
    ("pywin32",      "pywin32",      False),
]


def _check_package(import_name):
    """检测单个包是否可导入"""
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


def check_environment():
    """检测所有依赖状态，返回 (已安装列表, 缺失列表)"""
    installed = []
    missing = []
    for import_name, pip_name, required in DEPENDENCIES:
        if _check_package(import_name):
            installed.append((import_name, pip_name, required))
        else:
            missing.append((import_name, pip_name, required))
    return installed, missing


def _print_header(text):
    print()
    print("=" * 56)
    print(f"  {text}")
    print("=" * 56)


def _print_success(text):
    print(f"  [OK] {text}")


def _print_warn(text):
    print(f"  [!] {text}")


def _print_error(text):
    print(f"  [X] {text}")


def _print_info(text):
    print(f"  [*] {text}")


def install_packages(packages):
    """使用 pip 安装包列表"""
    pip_names = [p[1] for p in packages]
    _print_info(f"正在安装: {', '.join(pip_names)}")
    print()

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + pip_names

    try:
        # 使用实时输出，便于观察进度
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in process.stdout:
            print(f"  {line.rstrip()}")
        process.wait()

        if process.returncode == 0:
            _print_success("安装完成")
            return True
        else:
            _print_error(f"pip 安装失败 (退出码: {process.returncode})")
            return False
    except FileNotFoundError:
        _print_error("找不到 pip，请确认 Python 是否正确安装")
        return False
    except Exception as e:
        _print_error(f"安装过程出错: {e}")
        return False


def main():
    # ── 读取版本号 ──
    try:
        from paddle_ocr_tool import __version__ as app_version
    except ImportError:
        app_version = "?.?.?"

    print()
    print("  ╔══════════════════════════════════════════════╗")
    print(f"  ║    SnapPaddleOCR v{app_version:<7s} · 截图速识          ║")
    print("  ╚══════════════════════════════════════════════╝")

    # ── 必须在任何 paddle 导入前设置环境变量 ──
    os.environ["FLAGS_use_mkldnn"] = "0"
    os.environ["FLAGS_enable_pir_api"] = "0"
    os.environ["FLAGS_enable_pir_in_executor"] = "0"
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["PADDLE_PDX_CACHE_HOME"] = os.path.join(
        SCRIPT_DIR, ".paddlex_cache"
    )

    # 1. 检测 Python 版本
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    _print_info(f"Python {py_ver}")

    if sys.version_info < (3, 9):
        _print_error("需要 Python 3.9 或更高版本")
        input("\n  按 Enter 键退出...")
        sys.exit(1)

    # 2. 检测依赖
    _print_header("检测依赖环境")
    installed, missing = check_environment()

    for import_name, pip_name, required in installed:
        tag = "(必需)" if required else "(可选)"
        _print_success(f"{pip_name:20s} 已安装 {tag}")

    if not missing:
        _print_header("所有依赖已就绪，正在启动...")
        time.sleep(0.5)
    else:
        _print_header("以下模块缺失，需要安装")

        required_missing = [m for m in missing if m[2]]
        optional_missing = [m for m in missing if not m[2]]

        for import_name, pip_name, _ in required_missing:
            _print_error(f"{pip_name:20s} (必需)")

        for import_name, pip_name, _ in optional_missing:
            _print_warn(f"{pip_name:20s} (可选，全局热键/托盘需要)")

        print()

        # 3. 安装流程
        # 先安装所有必需的依赖
        if required_missing:
            _print_info("正在安装必需的依赖模块...")
            print("  (首次安装 PaddleOCR 可能需要几分钟，请耐心等待)")
            print()
            if not install_packages(required_missing):
                _print_header("必需模块安装失败")
                _print_warn("请尝试手动安装：")
                for _, pip_name, _ in required_missing:
                    print(f"    pip install {pip_name}")
                input("\n  按 Enter 键退出...")
                sys.exit(1)

        # 再安装可选依赖
        if optional_missing:
            _print_info("正在安装可选的增强模块...")
            install_packages(optional_missing)

        # 4. 再次验证
        _print_header("验证安装结果")
        _, still_missing = check_environment()
        still_required = [m for m in still_missing if m[2]]
        still_optional = [m for m in still_missing if not m[2]]

        for import_name, pip_name, _ in still_required:
            _print_error(f"{pip_name:20s} 仍未安装")

        for import_name, pip_name, _ in still_optional:
            _print_warn(f"{pip_name:20s} 未安装 (非必需)")

        if still_required:
            _print_header("必需依赖安装不完整，无法启动")
            input("\n  按 Enter 键退出...")
            sys.exit(1)

        if still_optional:
            _print_info("可选模块缺失不影响核心功能，可稍后手动安装")
            print()

        _print_success("环境准备完成")
        time.sleep(0.5)

    # 5. 启动主程序
    _print_header("启动 SnapPaddleOCR...")
    print()

    tool_dir = os.path.join(SCRIPT_DIR, "paddle_ocr_tool")
    sys.path.insert(0, tool_dir)
    os.chdir(tool_dir)

    from main import main as run_app
    run_app()


if __name__ == "__main__":
    # 禁用 pycache，避免产生遗留文件
    sys.dont_write_bytecode = True
    main()
