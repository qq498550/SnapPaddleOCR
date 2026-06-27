<p align="center">
  <h1 align="center">SnapPaddleOCR · 截图速识</h1>
  <p align="center">基于 PaddleOCR 引擎的 Windows 离线截图文字识别工具</p>
  <p align="center">
    <strong>🖼️ 截图即识 · 📋 剪贴板识别 · ⚡ 快速复制 · 🎯 高精度</strong>
  </p>
</p>

<div align="center">
  <img width="600" height="454" alt="Screenshot" src="https://github.com/user-attachments/assets/e386790f-d362-47b6-af16-a6fda6c09d8e" />
</div>

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| **截图OCR** | 框选屏幕任意区域，画面冻结后精准选取，即时识别文字 |
| **剪贴板OCR** | 直接识别剪贴板中的图片文字 |
| **快速OCR** | 截图后自动识别并复制结果，全程无弹窗 |
| **全局热键** | 自定义快捷键，任何界面下均可快速唤起识别 |
| **系统托盘** | 后台常驻运行，左键单击切换显示/隐藏 |
| **离线运行** | 模型内嵌安装包，无需联网下载 |
| **卡片式记录** | 识别结果以卡片列表展示，每条带独立复制按钮 |
| **Toast** | 屏幕下方圆角气泡弹窗，识别完成即时提示 |
| **CPU线程可调** | 自动检测核心数，可调线程数优化推理速度 |
| **开机自启** | 支持开机自动启动 |

## 🚀 快速开始

### 方式一：安装包（推荐）

下载发布的安装包，解压后双击 `SnapPaddleOCR.exe` 直接运行。无需 Python、无需联网。

### 方式二：开发环境

**环境要求**
- Windows 10 / 11 (64-bit)
- Python 3.9+

```bash
# 克隆项目
git clone <repo-url>
cd SnapPaddleOCR

# 创建虚拟环境
python -m venv .venv

# 安装依赖
.venv\Scripts\python.exe -m pip install -r paddle_ocr_tool\requirements.txt

# 启动（两种方式）
python run.py          # 直接启动
# 或
start.bat              # 带依赖检测的启动器
```

> 首次运行会自动下载 OCR 模型（约 130MB），请保持网络畅通。后续启动为离线模式。

### 默认快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Shift+F` | 截图OCR — 框选区域，识别文字 |
| `Ctrl+Shift+G` | 剪贴板OCR — 识别剪贴板中的图片 |
| `Ctrl+Shift+D` | 快速OCR — 截图识别并自动复制结果 |

> 快捷键可在设置面板中自定义修改。

## 🎮 使用指南

### 截图OCR

1. 按下 `Ctrl+Shift+F`（或点击 **截图OCR** 按钮）
2. 屏幕画面冻结，显示触发瞬间的静态截图
3. 按住左键拖选识别区域（橙色矩形框）
4. 松开鼠标，结果自动显示在主窗口卡片列表中
5. 如开启了自动复制，结果同时写入剪贴板

### 剪贴板OCR

- 复制任意图片到剪贴板（截图工具、浏览器图片等）
- 按下 `Ctrl+Shift+G`，自动识别剪贴板中的图片文字

### 快速OCR

- 按下 `Ctrl+Shift+D`，拖选区域后自动识别并复制结果
- 不弹出主窗口，适合快速提取文字的场景

## 🗂️ 项目结构

```
SnapPaddleOCR/
├── run.py                        # 应用入口（直接启动）
├── launcher.py                   # 启动器（带依赖检测安装）
├── start.bat                     # Windows 开发环境启动脚本
├── config.json                   # 用户配置文件
├── .paddlex_cache/               # PaddleOCR 模型缓存
└── paddle_ocr_tool/              # 核心包
    ├── __init__.py               # 包标识
    ├── paths.py                  # 集中路径管理（dev/frozen）
    ├── env_config.py             # 环境变量 & DPI 设置
    ├── config.py                 # 配置管理模块
    ├── main.py                   # 主程序（应用生命周期管理）
    ├── ocr_engine.py             # PaddleOCR 引擎封装
    ├── screenshot.py             # 截图捕获模块
    ├── hotkey.py                 # 全局热键管理器
    ├── requirements.txt          # Python 依赖列表
    └── ui/
        ├── __init__.py
        ├── main_window.py        # 主窗口界面
        ├── settings_window.py    # 设置对话框
        ├── tray.py               # 系统托盘
        └── main.ico              # 程序图标
```

## ⚙️ 配置说明

配置文件 `config.json` 可通过设置面板或直接编辑修改：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `language` | `ch` | 识别语言 |
| `device` | `cpu` | 推理设备 |
| `cpu_threads` | `24` | CPU 线程数（自动检测） |
| `enable_mkldnn` | `false` | 是否启用 MKLDNN |
| `screenshot_hotkey` | `ctrl+shift+f` | 截图OCR热键 |
| `clipboard_hotkey` | `ctrl+shift+g` | 剪贴板OCR热键 |
| `quick_ocr_hotkey` | `ctrl+shift+d` | 快速OCR热键 |
| `text_det_thresh` | `0.3` | 文本检测阈值 |
| `text_rec_score_thresh` | `0.5` | 识别置信度阈值 |
| `auto_copy` | `true` | 识别后自动复制 |
| `show_toast` | `true` | 显示Toast弹窗 |
| `autostart` | `false` | 开机自动启动 |
| `start_minimized` | `false` | 启动时隐藏主窗口 |
| `close_action` | `minimize` | 关闭窗口行为 |

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────┐
│              用户操作层                      │
│   全局热键(keyboard)  托盘菜单(pystray)     │
└─────────────┬───────────────────────────────┘
              ▼
┌─────────────────────────────────────────────┐
│             业务逻辑层 (main.py)             │
│   ┌──────────┐  ┌──────────┐  ┌─────────┐  │
│   │截图OCR   │  │剪贴板OCR │  │快速OCR  │  │
│   └─────┬────┘  └────┬─── ─┘  └───┬─────┘  │
└─────────┼──────────────┼───────────┼────────┘
          ▼              ▼           ▼
┌─────────────────────────────────────────────┐
│             引擎层                           │
│   ┌──────────────┐  ┌──────────────────┐    │
│   │  截图模块     │  │  OCR引擎         │    │
│   │ (PIL/Grab)   │→ │ (PaddleOCR/PaddleX)│   │
│   └──────────────┘  └──────────────────┘    │
└─────────────────────────────────────────────┘
```

### 核心依赖

| 组件 | 用途 |
|------|------|
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) 3.7+ | OCR 文字识别引擎，基于 PP-OCRv6 模型 |
| [PaddlePaddle](https://github.com/PaddlePaddle/Paddle) 3.3+ | 深度学习推理框架 |
| Pillow | 图像捕获与处理（屏幕截图、剪贴板读取） |
| keyboard | 全局热键注册 |
| pystray | 系统托盘图标 |
| cv2 / shapely / pyclipper | OCR 管道依赖 |

## 注意事项
- 初次运行如果有以下提示：
**OCR引擎初始化失败: PaddleOCR未安装: DLL load failed while importing \_pyclipper: 找不到指定的模块。** 请安装 [Microsoft Visual C++ Redistributable (2015-2022)](https://download.visualstudio.microsoft.com/download/pr/7ebf5fdb-36dc-4145-b0a0-90d3d5990a61/CC0FF0EB1DC3F5188AE6300FAEF32BF5BEEBA4BDD6E8E445A9184072096B713B/VC_redist.x64.exe)

## 📝 许可

本项目仅供学习参考，使用 PaddleOCR 和 PaddlePaddle 需遵守其相应的开源许可协议。
