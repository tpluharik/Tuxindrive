#ifndef AppVersion
  #define AppVersion "0.26.30"
#endif

[Setup]
AppId={{D8A63BC7-80D6-4D91-A350-22C5D86D90D8}
AppName=TuxInDrive
AppVersion={#AppVersion}
AppPublisher=TuxInDrive contributors
AppPublisherURL=https://github.com/tpluharik/TuxInDrive
DefaultDirName={localappdata}\Programs\TuxInDrive
DefaultGroupName=TuxInDrive
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=TuxInDrive-{#AppVersion}-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\branding\tuxindrive-icon.ico
UninstallDisplayIcon={app}\TuxInDrive.exe
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\..\build\windows\TuxInDrive\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\TuxInDrive"; Filename: "{app}\TuxInDrive.exe"
Name: "{userdesktop}\TuxInDrive"; Filename: "{app}\TuxInDrive.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "autostart"; Description: "Start TuxInDrive after sign-in"; GroupDescription: "Startup:"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "TuxInDrive"; ValueData: """{app}\TuxInDrive.exe"" --background"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\TuxInDrive.exe"; Description: "Launch TuxInDrive"; Flags: nowait postinstall skipifsilent
