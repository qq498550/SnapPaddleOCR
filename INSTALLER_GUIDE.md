# SnapPaddleOCR Windows 安装包制作指南

## 方法一：使用 Inno Setup（推荐）

1. 下载并安装 Inno Setup Compiler
   https://jrsoftware.org/isdl.php

2. 使用提供的 `setup.iss` 脚本编译安装包

3. 编译命令：
   ```
   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
   ```

## 方法二：手动分发

1. 将 `dist\SnapPaddleOCR` 整个文件夹复制给用户

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
