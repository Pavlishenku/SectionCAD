; =============================================================================
;  SectionCAD — installeur Windows PER-USER, SANS droits administrateur.
;  Inno Setup 6+. Compile : ISCC.exe installer.iss  (ou build_exe.ps1 -Installer)
; -----------------------------------------------------------------------------
;  Cle « sans admin » :
;    - PrivilegesRequired=lowest    -> aucune elevation UAC, installation utilisateur
;    - DefaultDirName={localappdata}\Programs\...  -> pas d'ecriture dans Program Files
;    - raccourcis dans {userprograms}/{userdesktop} -> ruche utilisateur (HKCU)
;  Alternative SANS installeur : le ZIP portable (dist\SectionCAD-portable.zip),
;  a extraire et lancer tel quel.
; =============================================================================

#define MyAppName "SectionCAD"
#define MyAppVersion "1.0.dev0"
#define MyAppPublisher "Pavlishenku"
#define MyAppExe "SectionCAD.exe"

[Setup]
AppId={{6F9A2C1E-7B3D-4E5F-8A1B-2C3D4E5F6A7B}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

; --- Installation PER-USER : aucun droit administrateur requis ---
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExe}

OutputDir=dist
OutputBaseFilename=SectionCAD-Setup-user
SetupIconFile=sectioncad.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Creer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
; Tout le dossier onedir produit par PyInstaller (dist\SectionCAD\).
Source: "dist\SectionCAD\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent
