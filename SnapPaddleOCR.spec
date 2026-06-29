# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

datas = [('F:\\VScode\\qq498550\\SnapPaddleOCR\\paddle_ocr_tool', 'paddle_ocr_tool'), ('F:\\VScode\\qq498550\\SnapPaddleOCR\\config.json', '.'), ('F:\\VScode\\qq498550\\SnapPaddleOCR\\.paddlex_cache', '.paddlex_cache')]
binaries = []
hiddenimports = ['PIL', 'PIL.ImageTk', 'pystray', 'keyboard', 'win32api', 'win32con', 'win32gui', 'tkinter', 'tkinter.ttk', 'tkinter.font', 'tkinter.scrolledtext', 'cv2', 'shapely', 'shapely.geometry', 'pyclipper', 'numpy', 'numpy.core', 'pypdfium2', 'pypdfium2_raw', 'python_bidi', 'imagesize']
datas += copy_metadata('shapely')
datas += copy_metadata('pyclipper')
datas += copy_metadata('pypdfium2')
datas += copy_metadata('python-bidi')
datas += copy_metadata('imagesize')
datas += copy_metadata('opencv-contrib-python')
tmp_ret = collect_all('paddleocr')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('paddle')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('paddlex')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cv2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyclipper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['F:\\VScode\\qq498550\\SnapPaddleOCR\\run.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SnapPaddleOCR',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['F:\\VScode\\qq498550\\SnapPaddleOCR\\paddle_ocr_tool\\ui\\main.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SnapPaddleOCR',
)
