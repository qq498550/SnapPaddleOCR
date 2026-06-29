; Inno Setup Script for SnapPaddle
; 用于创建 Windows 安装包的编译脚本

; 版本号与 paddle_ocr_tool/__init__.py 中的 __version__ 保持同步
#define MyAppName "SnapPaddleOCR"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "SnapPaddleOCR Team"
#define MyAppExeName "SnapPaddleOCR.exe"

[Setup]
; 基础设置
AppId={{A3B5C7D9-1234-5678-ABCD-EF0123456789}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=
OutputDir=installer_output
OutputBaseFilename=SnapPaddleOCR_Setup_{#MyAppVersion}
SetupIconFile=compiler_files\main.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

; 语言设置
Languages:
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl"

; 安装步骤
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
; 主程序目录（从 dist 目录复制）
Source: "dist\SnapPaddleOCR\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 注意：_internal 目录包含所有 Python 依赖和 PaddleOCR 模型

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
; 安装完成后询问是否启动程序
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// 自定义安装逻辑
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // 检查操作系统版本（需要 Windows 10 或更高）
  if (Win32MajorVersion < 10) then
  begin
    MsgBox('此应用程序需要 Windows 10 或更高版本。', mbError, MB_OK);
    Result := False;
  end
  else
    Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 安装后可以在这里执行额外的配置
  end;
end;
