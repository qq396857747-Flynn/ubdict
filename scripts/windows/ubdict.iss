#ifndef AppVersion
  #define AppVersion "0.1.12"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\..\dist\UbDict"
#endif

[Setup]
AppId={{C9672E99-97B4-4F68-940B-9A1E58F2D012}
AppName=UbDict
AppVersion={#AppVersion}
AppPublisher=UbDict
DefaultDirName={localappdata}\Programs\UbDict
DefaultGroupName=UbDict
UninstallDisplayIcon={app}\UbDict.exe
OutputDir=..\..\dist
OutputBaseFilename=UbDictSetup-{#AppVersion}-x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\UbDict"; Filename: "{app}\UbDict.exe"
Name: "{autodesktop}\UbDict"; Filename: "{app}\UbDict.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\UbDict.exe"; Description: "Launch UbDict"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'UbDict');
end;
