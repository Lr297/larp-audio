[Setup]
AppName=LARP Audio
AppVersion=0.1.0
AppPublisher=LARP Audio
AppPublisherURL=https://larpaudio.local/
DefaultDirName={autopf}\LARP Audio
DefaultGroupName=LARP Audio
UninstallDisplayIcon={app}\LARP Audio.exe
Compression=lzma2
SolidCompression=yes
OutputDir=..\Output
OutputBaseFilename=LARP-Audio-Windows-x64-Setup
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
SetupIconFile=..\resources\icons\larp_audio_master.ico
PrivilegesRequired=lowest

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The main executable and all its dependencies
Source: "..\dist\LARP Audio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Exclude macOS binaries explicitly
Excludes: "*macos-arm64*", "*.app", "*.dmg"

[Icons]
Name: "{group}\LARP Audio"; Filename: "{app}\LARP Audio.exe"; IconFilename: "{app}\LARP Audio.exe"
Name: "{group}\{cm:UninstallProgram,LARP Audio}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LARP Audio"; Filename: "{app}\LARP Audio.exe"; IconFilename: "{app}\LARP Audio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LARP Audio.exe"; Description: "{cm:LaunchProgram,LARP Audio}"; Flags: nowait postinstall skipifsilent
