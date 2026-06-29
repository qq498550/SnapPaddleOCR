
@echo off
chcp 936 >nul
set SCRIPT_DIR=%~dp0
set TARGET=%SCRIPT_DIR%SnapPaddleOCR\SnapPaddleOCR.exe
set SHORTCUT_NAME=SnapPaddleOCR 截图速识

echo 正在创建桌面快捷方式...

powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%USERPROFILE%\Desktop\%SHORTCUT_NAME%.lnk'); $Shortcut.TargetPath='%TARGET%'; $Shortcut.WorkingDirectory='%SCRIPT_DIR%SnapPaddleOCR'; $Shortcut.Description='SnapPaddleOCR 截图文字识别工具'; $Shortcut.Save()"

if exist "%USERPROFILE%\Desktop\%SHORTCUT_NAME%.lnk" (
    echo [OK] 快捷方式已创建到桌面
) else (
    echo [X] 快捷方式创建失败
)

pause
