; Inno Setup script: wraps dist\pdfdesk into dist\pdfdesk-setup-<version>.exe
; Build: iscc /DMyAppVersion=0.1.0 packaging\pdfdesk.iss
[Setup]
AppName=pdfdesk
AppVersion={#MyAppVersion}
AppId=pdfdesk
DefaultDirName={autopf}\pdfdesk
DefaultGroupName=pdfdesk
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=pdfdesk-setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
Name: pdfassoc; Description: "Add pdfdesk to ""Open with"" for PDF files"

[Files]
Source: "..\dist\pdfdesk\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\pdfdesk"; Filename: "{app}\pdfdesk.exe"
Name: "{autodesktop}\pdfdesk"; Filename: "{app}\pdfdesk.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "pdfdesk.pdf"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\pdfdesk.pdf\shell\open\command"; ValueType: string; ValueData: """{app}\pdfdesk.exe"" ""%1"""; Flags: uninsdeletekey; Tasks: pdfassoc

[Run]
Filename: "{app}\pdfdesk.exe"; Description: "Start pdfdesk"; Flags: nowait postinstall skipifsilent
