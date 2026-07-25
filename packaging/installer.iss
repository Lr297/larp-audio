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
SetupIconFile=..\resources\icons\larp-audio.ico
PrivilegesRequired=lowest

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\LARP Audio\*"; DestDir: "{app}"; Excludes: "*macos-arm64*,*.app,*.dmg"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LARP Audio"; Filename: "{app}\LARP Audio.exe"; IconFilename: "{app}\LARP Audio.exe"
Name: "{group}\{cm:UninstallProgram,LARP Audio}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LARP Audio"; Filename: "{app}\LARP Audio.exe"; IconFilename: "{app}\LARP Audio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LARP Audio.exe"; Description: "{cm:LaunchProgram,LARP Audio}"; Flags: nowait postinstall skipifsilent
