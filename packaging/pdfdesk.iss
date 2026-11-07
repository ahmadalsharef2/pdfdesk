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
Name: shellmenu; Description: "Add ""Combine files"" and ""Convert to PDF"" to the Explorer right-click menu"

[Files]
Source: "..\dist\pdfdesk\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\pdfdesk"; Filename: "{app}\pdfdesk.exe"
Name: "{autodesktop}\pdfdesk"; Filename: "{app}\pdfdesk.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "pdfdesk.pdf"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\pdfdesk.pdf\shell\open\command"; ValueType: string; ValueData: """{app}\pdfdesk.exe"" ""%1"""; Flags: uninsdeletekey; Tasks: pdfassoc

; Explorer right-click entries. Explorer starts pdfdesk once per selected file; the launches find each other
; (pdfdesk/instance.py) and the files end up in one Combine dialog. Windows 11: under "Show more options".
Root: HKA; Subkey: "Software\Classes\*\shell\pdfdesk.combine"; ValueType: string; ValueName: ""; ValueData: "Combine files in pdfdesk"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\pdfdesk.combine"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\pdfdesk.exe"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\pdfdesk.combine"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\pdfdesk.combine"; ValueType: string; ValueName: "AppliesTo"; ValueData: "System.FileExtension:=.pdf OR System.FileExtension:=.bmp OR System.FileExtension:=.cbz OR System.FileExtension:=.csv OR System.FileExtension:=.doc OR System.FileExtension:=.docx OR System.FileExtension:=.dps OR System.FileExtension:=.epub OR System.FileExtension:=.et OR System.FileExtension:=.fb2 OR System.FileExtension:=.gif OR System.FileExtension:=.htm OR System.FileExtension:=.html OR System.FileExtension:=.jp2 OR System.FileExtension:=.jpeg OR System.FileExtension:=.jpg OR System.FileExtension:=.jxr OR System.FileExtension:=.key OR System.FileExtension:=.numbers OR System.FileExtension:=.odg OR System.FileExtension:=.odp OR System.FileExtension:=.ods OR System.FileExtension:=.odt OR System.FileExtension:=.pages OR System.FileExtension:=.png OR System.FileExtension:=.pnm OR System.FileExtension:=.ppt OR System.FileExtension:=.pptx OR System.FileExtension:=.rtf OR System.FileExtension:=.svg OR System.FileExtension:=.tif OR System.FileExtension:=.tiff OR System.FileExtension:=.txt OR System.FileExtension:=.vsd OR System.FileExtension:=.vsdx OR System.FileExtension:=.webp OR System.FileExtension:=.wpd OR System.FileExtension:=.wps OR System.FileExtension:=.xhtml OR System.FileExtension:=.xls OR System.FileExtension:=.xlsx OR System.FileExtension:=.xps"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\pdfdesk.combine\command"; ValueType: string; ValueData: """{app}\pdfdesk.exe"" --combine ""%1"""; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\pdfdesk.convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF in pdfdesk"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\pdfdesk.convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\pdfdesk.exe"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\pdfdesk.convert"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\pdfdesk.convert"; ValueType: string; ValueName: "AppliesTo"; ValueData: "System.FileExtension:=.bmp OR System.FileExtension:=.cbz OR System.FileExtension:=.csv OR System.FileExtension:=.doc OR System.FileExtension:=.docx OR System.FileExtension:=.dps OR System.FileExtension:=.epub OR System.FileExtension:=.et OR System.FileExtension:=.fb2 OR System.FileExtension:=.gif OR System.FileExtension:=.htm OR System.FileExtension:=.html OR System.FileExtension:=.jp2 OR System.FileExtension:=.jpeg OR System.FileExtension:=.jpg OR System.FileExtension:=.jxr OR System.FileExtension:=.key OR System.FileExtension:=.numbers OR System.FileExtension:=.odg OR System.FileExtension:=.odp OR System.FileExtension:=.ods OR System.FileExtension:=.odt OR System.FileExtension:=.pages OR System.FileExtension:=.png OR System.FileExtension:=.pnm OR System.FileExtension:=.ppt OR System.FileExtension:=.pptx OR System.FileExtension:=.rtf OR System.FileExtension:=.svg OR System.FileExtension:=.tif OR System.FileExtension:=.tiff OR System.FileExtension:=.txt OR System.FileExtension:=.vsd OR System.FileExtension:=.vsdx OR System.FileExtension:=.webp OR System.FileExtension:=.wpd OR System.FileExtension:=.wps OR System.FileExtension:=.xhtml OR System.FileExtension:=.xls OR System.FileExtension:=.xlsx OR System.FileExtension:=.xps"; Flags: uninsdeletekey; Tasks: shellmenu
Root: HKA; Subkey: "Software\Classes\*\shell\pdfdesk.convert\command"; ValueType: string; ValueData: """{app}\pdfdesk.exe"" --convert ""%1"""; Flags: uninsdeletekey; Tasks: shellmenu

[Run]
Filename: "{app}\pdfdesk.exe"; Description: "Start pdfdesk"; Flags: nowait postinstall skipifsilent
