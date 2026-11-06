"""
SnapPaddleOCR · 截图速识 - PyInstaller 打包脚本（精简版）

体积优化策略：
  1. 仅内嵌默认轻量档模型（约 22MB），标准档（约 133MB）不内嵌，
     用户在设置中选择标准档时才联网下载
  2. 打包后删除运行期用不到的文件（头文件 / 导入库 / 类型存根 /
     OpenCV 视频与级联数据 / hf_xet 等），已逐项实测验证
  3. 打包完成后自动运行 exe 自检（--selftest），确保精简未破坏功能
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.resolve()
TOOL_DIR = PROJECT_ROOT / "paddle_ocr_tool"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
APP_DIR = DIST_DIR / "SnapPaddleOCR"

# 精简项（路径相对 dist/SnapPaddleOCR，均已实测不影响运行）
SLIM_DIRS = [
    "_internal/paddle/include",   # C++ 头文件，运行期不需要
    "_internal/cv2/data",         # 人脸/级联分类器数据，本项目不使用
]

SLIM_GLOBS = [
    "_internal/paddle/**/*.lib",          # 导入库（仅编译期使用）
    "_internal/paddle/**/*.pyi",          # 类型存根（运行期不加载）
    "_internal/cv2/opencv_videoio_ffmpeg*.dll",  # 视频编解码，OCR 不用
    "_internal/PIL/_avif*.pyd",           # AVIF 解码插件
]

# 内嵌的轻量档模型（默认档，随安装包分发，离线可用）
BUNDLED_MODELS = [
    "PP-OCRv4_mobile_det",
    "PP-OCRv4_mobile_rec",
    "PP-LCNet_x1_0_textline_ori",
]
MODELS_SRC = PROJECT_ROOT / ".paddlex_cache" / "official_models"


# ── 读取应用版本号 ──
def _get_version():
    """从 paddle_ocr_tool/__init__.py 读取版本号"""
    init_file = TOOL_DIR / "__init__.py"
    if init_file.exists():
        content = init_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.startswith("__version__"):
                return line.split("=")[-1].strip().strip('"').strip("'")
    return "0.0.0"


APP_VERSION = _get_version()


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def clean_build_dirs():
    """清理旧的构建目录"""
    print("[*] 清理旧的构建目录...")
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            shutil.rmtree(d)
            print(f"    已删除：{d}")


def generate_icon_if_needed():
    """检查图标文件是否存在"""
    icon_path = TOOL_DIR / "ui" / "main.ico"
    if not icon_path.exists():
        print("[!] 警告：图标文件不存在，将使用默认图标")
        return None
    print(f"[+] 图标文件：{icon_path}")
    return str(icon_path)


def build_pyinstaller():
    """执行 PyInstaller 打包"""
    icon_path = generate_icon_if_needed()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "SnapPaddleOCR",
        "--onedir",
        "--windowed",
    ]

    if icon_path:
        cmd += ["--icon", icon_path]

    # 代码与配置 + 默认轻量档模型（标准档不内嵌，选择时才联网下载）
    cmd += [
        "--add-data", f"{TOOL_DIR}{os.pathsep}paddle_ocr_tool",
        "--add-data", f"{PROJECT_ROOT / 'config.json'}{os.pathsep}.",
    ]
    bundled = []
    for name in BUNDLED_MODELS:
        src = MODELS_SRC / name
        if src.is_dir():
            cmd += [
                "--add-data",
                f"{src}{os.pathsep}.paddlex_cache/official_models/{name}",
            ]
            bundled.append(name)
        else:
            print(f"[!] 警告：内置模型缺失，该档位将需要联网下载: {name}")
    if bundled:
        size = sum(_dir_size_mb(MODELS_SRC / n) for n in bundled)
        print(f"[+] 内嵌轻量档模型 {len(bundled)} 个（约 {size:.0f} MB）: {bundled}")
    else:
        print("[X] 未找到任何可内嵌模型！请先在开发环境运行一次以下载模型")

    cmd += [
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.ImageTk",
        "--hidden-import", "pystray",
        "--hidden-import", "keyboard",
        # 二维码/条形码解码（懒加载，需显式声明）
        "--hidden-import", "zxingcpp",
        "--hidden-import", "win32api",
        "--hidden-import", "win32con",
        "--hidden-import", "win32gui",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.font",
        "--hidden-import", "tkinter.scrolledtext",
        # PaddleX OCR 管道依赖 (ocr-core 必需)
        "--hidden-import", "cv2",
        "--hidden-import", "shapely",
        "--hidden-import", "shapely.geometry",
        "--hidden-import", "pyclipper",
        "--hidden-import", "numpy",
        "--hidden-import", "numpy.core",
        "--hidden-import", "pypdfium2",
        "--hidden-import", "pypdfium2_raw",
        "--hidden-import", "python_bidi",
        "--hidden-import", "imagesize",
        # 首次运行下载模型所需的网络栈（PaddleX 动态导入，PyInstaller 静态
        # 分析会漏掉，缺失时表现为 "No model source is available"）
        "--hidden-import", "requests",
        "--hidden-import", "requests.adapters",
        "--hidden-import", "urllib3",
        "--hidden-import", "idna",
        "--hidden-import", "filelock",
        "--hidden-import", "fsspec",
        "--hidden-import", "huggingface_hub",
        "--hidden-import", "tqdm",
        # hf_xet 仅用于 HuggingFace 加速传输，PaddleX 官方源下载不需要
        "--exclude-module", "hf_xet",
        "--collect-all", "paddleocr",
        "--collect-all", "paddle",
        "--collect-all", "paddlex",
        "--collect-all", "cv2",
        "--collect-all", "pyclipper",
        # 复制包元数据（PaddleX 用 importlib.metadata 检查依赖）
        "--copy-metadata", "shapely",
        "--copy-metadata", "pyclipper",
        "--copy-metadata", "pypdfium2",
        "--copy-metadata", "python-bidi",
        "--copy-metadata", "imagesize",
        "--copy-metadata", "opencv-contrib-python",
        "--noconfirm",
        "--clean",
        str(PROJECT_ROOT / "run.py"),
    ]

    print("[*] 执行 PyInstaller 打包...")
    print(f"    命令：{' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    if result.returncode == 0:
        print("\n[+] 打包成功!")
        print(f"    输出目录：{APP_DIR}")
        return True

    print("\n[X] 打包失败!")
    return False


def slim_dist():
    """删除运行期不需要的文件，减小分发体积"""
    before = _dir_size_mb(APP_DIR)
    print("[*] 精简分发包（删除运行期不需要的文件）...")

    removed = []
    for rel in SLIM_DIRS:
        target = APP_DIR / rel
        if target.exists():
            size = _dir_size_mb(target)
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
            if not target.exists():
                removed.append((rel, size))

    for pattern in SLIM_GLOBS:
        for f in APP_DIR.glob(pattern):
            if f.is_file():
                size = f.stat().st_size / (1024 * 1024)
                try:
                    f.unlink()
                    removed.append((str(f.relative_to(APP_DIR)), size))
                except OSError:
                    pass

    # 清理空目录
    for d in sorted(APP_DIR.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            try:
                d.rmdir()
            except OSError:
                pass

    total = sum(s for _, s in removed)
    after = _dir_size_mb(APP_DIR)
    for name, size in sorted(removed, key=lambda x: -x[1])[:10]:
        print(f"    - {name}  ({size:.1f} MB)")
    print(f"[+] 精简完成：{before:.0f} MB -> {after:.0f} MB（减少 {total:.0f} MB）")
    return after


def run_selftest() -> bool:
    """运行打包产物自检：验证精简后 OCR 链路仍可用"""
    exe = APP_DIR / "SnapPaddleOCR.exe"
    log = APP_DIR / "_selftest.log"
    if log.exists():
        log.unlink()
    print("[*] 运行打包产物自检（--selftest）...")
    env = os.environ.copy()
    # 复用构建机已下载模型，自检不触发下载
    env["PADDLE_PDX_CACHE_HOME"] = str(PROJECT_ROOT / ".paddlex_cache")
    try:
        proc = subprocess.run([str(exe), "--selftest"], cwd=str(APP_DIR),
                              env=env, timeout=600)
    except subprocess.TimeoutExpired:
        print("[X] 自检超时")
        return False

    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    ok = proc.returncode == 0 and "SELFTEST OK" in text
    for line in text.splitlines()[-6:]:
        print(f"    {line}")
    if ok:
        print("[+] 自检通过：精简后 OCR 推理链路正常")
    else:
        print(f"[X] 自检失败（exit={proc.returncode}）")
    if log.exists():
        log.unlink()
    return ok


def create_shortcut_script():
    """创建快捷方式创建脚本"""
    script_content = '''
@echo off
chcp 936 >nul
set SCRIPT_DIR=%~dp0
set TARGET=%SCRIPT_DIR%SnapPaddleOCR\\SnapPaddleOCR.exe
set SHORTCUT_NAME=SnapPaddleOCR 截图速识

echo 正在创建桌面快捷方式...

powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%USERPROFILE%\\Desktop\\%SHORTCUT_NAME%.lnk'); $Shortcut.TargetPath='%TARGET%'; $Shortcut.WorkingDirectory='%SCRIPT_DIR%SnapPaddleOCR'; $Shortcut.Description='SnapPaddleOCR 截图文字识别工具'; $Shortcut.Save()"

if exist "%USERPROFILE%\\Desktop\\%SHORTCUT_NAME%.lnk" (
    echo [OK] 快捷方式已创建到桌面
) else (
    echo [X] 快捷方式创建失败
)

pause
'''
    script_path = PROJECT_ROOT / "create_shortcut.bat"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_content)
    print(f"[+] 快捷方式脚本已创建：{script_path}")


def create_installer_script():
    """创建安装包制作说明"""
    content = '''# SnapPaddleOCR Windows 安装包制作指南

## 方法一：使用 Inno Setup（推荐）

1. 下载并安装 Inno Setup Compiler
   https://jrsoftware.org/isdl.php

2. 使用提供的 `setup.iss` 脚本编译安装包

3. 编译命令：
   ```
   "C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe" setup.iss
   ```

## 方法二：手动分发

1. 将 `dist\\SnapPaddleOCR` 整个文件夹复制给用户

2. 用户可直接运行 `SnapPaddleOCR.exe`

## 系统要求

- Windows 10 / 11 (64-bit)
- 无需安装 Python 或任何依赖
- 默认轻量档模型已内置，开箱即用、完全离线；安装包内置模型在首次
  运行时同步到 `%LOCALAPPDATA%\\SnapPaddleOCR\\models`
- 在设置中切换"标准"档位时才需联网下载（约 133 MB），之后可离线使用

## 文件结构

```
SnapPaddleOCR/
├── SnapPaddleOCR.exe    # 主程序
└── _internal/
    ├── config.json      # 配置文件
    ├── .paddlex_cache/  # 内置轻量档模型（离线可用）
    └── ...              # 运行时依赖库（标准档模型按需下载）
```
'''
    guide_path = PROJECT_ROOT / "INSTALLER_GUIDE.md"
    with open(guide_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[+] 安装包指南已创建：{guide_path}")


def main():
    print("=" * 60)
    print(f"  SnapPaddleOCR v{APP_VERSION} · Windows 打包工具")
    print("=" * 60)
    print()

    try:
        import PyInstaller
        print(f"[+] PyInstaller 版本：{PyInstaller.__version__}")
    except ImportError:
        print("[X] PyInstaller 未安装，请先运行：pip install pyinstaller")
        sys.exit(1)

    clean_build_dirs()

    if not build_pyinstaller():
        print("\n打包失败，请检查错误日志")
        sys.exit(1)

    slim_dist()

    self_test_ok = run_selftest()

    create_shortcut_script()
    create_installer_script()

    print("\n" + "=" * 60)
    print("  打包完成!")
    print("=" * 60)
    print(f"\n可执行文件位置：{APP_DIR / 'SnapPaddleOCR.exe'}")
    print(f"分发体积：约 {_dir_size_mb(APP_DIR):.0f} MB（不含模型，首次运行自动下载）")
    print("\n下一步:")
    print("  1. 测试运行 dist/SnapPaddleOCR/SnapPaddleOCR.exe")
    print("  2. 使用 create_shortcut.bat 创建桌面快捷方式")
    print("  3. 参考 INSTALLER_GUIDE.md 制作安装包")
    if not self_test_ok:
        print("\n[!] 注意：产物自检未通过，请勿直接发布")


if __name__ == "__main__":
    main()
