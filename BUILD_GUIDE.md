# SnapPaddleOCR · 截图速识 - Windows 编译与打包指南

本指南详细说明如何在 Windows 环境下将 SnapPaddleOCR 构建为独立的可执行应用程序。

## 📋 前置要求

### 开发环境
- **操作系统**: Windows 10 / 11 (64-bit)
- **Python**: 3.9 或更高版本 (推荐 3.10+)
- **Git**: 用于克隆代码仓库

### 必要工具
```bash
# 安装 Python 依赖
pip install -r paddle_ocr_tool/requirements.txt

# 安装打包工具
pip install pyinstaller>=5.0.0
```

## 🏗️ 编译步骤

### 方法一：使用自动化脚本（推荐）

1. **打开命令提示符或 PowerShell**
   ```cmd
   cd C:\path\to\SnapPaddleOCR
   ```

2. **运行打包脚本**
   ```cmd
   python build_windows.py
   ```

3. **等待构建完成**
   - 首次构建可能需要 5-10 分钟（下载 PaddleOCR 模型）
   - 构建完成后，可执行文件位于 `dist/SnapPaddleOCR/`

### 方法二：手动执行 PyInstaller

```cmd
pyinstaller --name SnapPaddleOCR ^
            --onedir ^
            --windowed ^
            --icon paddle_ocr_tool/ui/main.ico ^
            --add-data "paddle_ocr_tool;paddle_ocr_tool" ^
            --add-data "config.json;." ^
            --hidden-import PIL ^
            --hidden-import pystray ^
            --hidden-import keyboard ^
            --hidden-import win32api ^
            --hidden-import win32con ^
            --hidden-import win32gui ^
            --collect-all paddleocr ^
            --collect-all paddle ^
            --noconfirm ^
            --clean ^
            run.py
```

## 📦 输出说明

### 构建产物
```
dist/
└── SnapPaddleOCR/
    ├── SnapPaddleOCR.exe    # 主程序入口
    ├── config.json         # 默认配置文件
    └── _internal/          # 运行时依赖库
        ├── paddleocr/      # OCR 引擎
        ├── paddle/         # 深度学习框架
        ├── PIL/            # 图像处理库
        └── ...             # 其他依赖
```

### 文件大小
- **完整目录大小**: 约 800MB - 1.2GB
  - 主要体积来自 PaddlePaddle 和 PaddleOCR 模型
  - 模型会在首次运行时下载到 `.paddlex_cache/`

## 🔧 制作安装包（可选）

### 使用 Inno Setup

1. **下载并安装 Inno Setup**
   - 官网：https://jrsoftware.org/isdl.php

2. **准备图标文件**
   ```cmd
   mkdir compiler_files
   copy paddle_ocr_tool/ui/main.ico compiler_files/
   ```

3. **编译安装包**
   ```cmd
   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
   ```

4. **输出位置**
   - 安装包位于：`installer_output/SnapPaddleOCR_Setup_1.0.0.exe`

### 简易分发方式

直接复制整个 `dist/SnapPaddleOCR/` 文件夹给用户即可，无需安装。

## ✅ 验证构建

### 测试运行
```cmd
cd dist\SnapPaddleOCR
SnapPaddleOCR.exe
```

### 检查项目
- [ ] 程序正常启动，无错误弹窗
- [ ] 系统托盘图标显示正常
- [ ] 快捷键可以注册（需要管理员权限）
- [ ] 截图 OCR 功能正常工作
- [ ] 剪贴板 OCR 功能正常工作
- [ ] 设置窗口可以打开并保存配置

## ⚠️ 常见问题

### 1. 构建时提示找不到模块
```
ModuleNotFoundError: No module named 'xxx'
```
**解决**: 在 `build_windows.py` 的 `--hidden-import` 列表中添加该模块

### 2. 运行时提示缺少 DLL 文件
```
ImportError: DLL load failed while importing xxx
```
**解决**: 
- 确保已安装 Visual C++ Redistributable
- 下载地址：https://aka.ms/vs/17/release/vc_redist.x64.exe

### 3. 程序启动后立即退出
**可能原因**:
- 缺少必要的依赖包
- 模型缓存目录权限问题

**解决**:
```cmd
# 以管理员身份运行一次，创建必要的文件和目录
runas /user:administrator "dist\SnapPaddleOCR\SnapPaddleOCR.exe"
```

### 4. 打包后体积过大
**优化建议**:
- 使用 `--onefile` 模式（但启动会变慢）
- 排除不需要的 Paddle 组件（需测试兼容性）
- 使用 UPX 压缩（可能影响稳定性）

## 📝 版本发布清单

发布新版本前请确认：

- [ ] 更新 `setup.iss` 中的版本号
- [ ] 测试所有核心功能
- [ ] 在无 Python 环境的干净 Windows 系统中测试
- [ ] 准备更新日志
- [ ] 签名可执行文件（可选，需要代码签名证书）

## 🔐 代码签名（可选）

如需正式分发，建议使用代码签名证书对可执行文件进行签名：

```cmd
signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com dist\SnapPaddleOCR\SnapPaddleOCR.exe
```

## 📄 许可证

本项目使用的 PaddleOCR 和 PaddlePaddle 遵循其各自的开源许可证。
构建和分发时请遵守相关许可协议。

---

**技术支持**: 如有问题，请参考项目 README.md 或提交 Issue。
