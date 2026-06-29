"""
SnapPaddleOCR · 截图速识 - PyInstaller 打包脚本
用于构建 Windows  standalone 可执行文件
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.resolve()
TOOL_DIR = PROJECT_ROOT / "paddle_ocr_tool"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"

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
    
    # 模型缓存（内嵌到安装包，开箱即用）
    cache_src = PROJECT_ROOT / ".paddlex_cache"
    cache_data = None
    if cache_src.exists():
        cache_data = f"{cache_src}{os.pathsep}.paddlex_cache"
        print(f"[+] 模型缓存: {cache_src}")

    # PyInstaller 命令参数
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "SnapPaddleOCR",
        "--onedir",  # 单目录模式
        "--windowed",  # 无控制台窗口
    ]

    if icon_path:
        cmd += ["--icon", icon_path]

    cmd += [
        "--add-data", f"{TOOL_DIR}{os.pathsep}paddle_ocr_tool",
        "--add-data", f"{PROJECT_ROOT / 'config.json'}{os.pathsep}.",
    ]

    if cache_data:
        cmd += ["--add-data", cache_data]

    cmd += [
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.ImageTk",
        "--hidden-import", "pystray",
        "--hidden-import", "keyboard",
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
        print(f"    输出目录：{DIST_DIR / 'SnapPaddleOCR'}")
        return True
    else:
        print("\n[X] 打包失败!")
        return False

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
- 内置 OCR 模型，无需联网下载

## 文件结构

```
SnapPaddleOCR/
├── SnapPaddleOCR.exe    # 主程序
├── config.json          # 配置文件
├── .paddlex_cache/      # 内置 OCR 模型
└── _internal/           # 运行时依赖库
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
    
    # 检查 PyInstaller
    try:
        import PyInstaller
        print(f"[+] PyInstaller 版本：{PyInstaller.__version__}")
    except ImportError:
        print("[X] PyInstaller 未安装，请先运行：pip install pyinstaller")
        sys.exit(1)
    
    # 清理旧构建
    clean_build_dirs()
    
    # 执行打包
    success = build_pyinstaller()
    
    if success:
        # 创建辅助脚本
        create_shortcut_script()
        create_installer_script()
        
        print("\n" + "=" * 60)
        print("  打包完成!")
        print("=" * 60)
        print(f"\n可执行文件位置：{DIST_DIR / 'SnapPaddleOCR' / 'SnapPaddleOCR.exe'}")
        print("\n下一步:")
        print("  1. 测试运行 dist/SnapPaddleOCR/SnapPaddleOCR.exe")
        print("  2. 使用 create_shortcut.bat 创建桌面快捷方式")
        print("  3. 参考 INSTALLER_GUIDE.md 制作安装包")
    else:
        print("\n打包失败，请检查错误日志")
        sys.exit(1)

if __name__ == "__main__":
    main()
