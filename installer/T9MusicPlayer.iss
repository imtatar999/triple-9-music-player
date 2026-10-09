; Inno Setup script for T9 Music Player.
; Built by build.py:  ISCC /DAppVersion=1.2.3 installer\T9MusicPlayer.iss
;
; Updating = running a newer setup. AppId never changes, so Windows treats it as
; the same program: files are replaced in place, shortcuts stay, and the user's
; library / playlists / settings in %APPDATA%\T9 Music Player are untouched.

#define AppName "Triple 9 Music Player"
; folder names stay as they were, so updates land in the same place and the data is found
#define DirName "T9 Music Player"
#define AppExe "T9 Music Player.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; never change this id - it is what makes a newer setup an update
AppId={{8F3C2A51-9D7E-4B6A-A1C9-2E5F7D3B9C40}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Triplenine
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
; per-user install: no administrator rights needed, also for updates
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#DirName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=T9MusicPlayer-Setup-{#AppVersion}
SetupIconFile=..\assets\t9.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; close a running player before replacing its files (Windows Restart Manager)
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "openwith"; Description: "Show {#AppName} in ""Open with"" for audio files"; GroupDescription: "Windows integration:"

[InstallDelete]
; an update replaces the whole runtime so no stale library files are left behind
Type: filesandordirs; Name: "{app}\_internal"
; shortcuts from before the name change (T9 Music Player -> Triple 9 Music Player)
Type: files; Name: "{autoprograms}\T9 Music Player.lnk"
Type: files; Name: "{autodesktop}\T9 Music Player.lnk"

[Files]
Source: "..\dist\T9 Music Player\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; "Open with" entry - does not take over the default player for any file type
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\DefaultIcon"; ValueType: string; ValueData: """{app}\{#AppExe}"",0"; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.mp3\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.flac\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.wav\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.m4a\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.aac\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.ogg\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.opus\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.wma\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.aif\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.aiff\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.ape\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.wv\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.dsf\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.m3u\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.m3u8\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith

[Run]
; also runs after a silent update, so the player comes back by itself
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\{#DirName}');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Also delete your library, playlists, play counts and settings?' + #13#10 + #13#10 +
                'Choose No to keep them for a later reinstall.' + #13#10 + DataDir,
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
