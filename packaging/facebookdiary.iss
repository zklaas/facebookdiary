; Inno Setup script: the Windows installer for FacebookDiary.
; Built by .github/workflows/release.yml from PyInstaller's dist\FacebookDiary folder:
;   iscc /DAppVersion=1.0.0 packaging\facebookdiary.iss
; Installs for the current user only (no administrator rights), adds a Start-menu
; entry and an uninstaller (Settings > Apps).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B4F1B00A-1610-5873-8676-0ABC0B651EF8}
AppName=FacebookDiary
AppVersion={#AppVersion}
AppPublisher=Zachary Klaas
AppPublisherURL=https://github.com/zklaas/facebookdiary
DefaultDirName={localappdata}\Programs\FacebookDiary
DefaultGroupName=FacebookDiary
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=FacebookDiary-Setup-Windows
SetupIconFile=..\icons\facebookdiary.ico
UninstallDisplayIcon={app}\FacebookDiary.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\FacebookDiary\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\FacebookDiary"; Filename: "{app}\FacebookDiary.exe"
Name: "{userdesktop}\FacebookDiary"; Filename: "{app}\FacebookDiary.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\FacebookDiary.exe"; Description: "Start FacebookDiary"; Flags: nowait postinstall skipifsilent
