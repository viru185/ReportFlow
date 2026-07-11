; Inno Setup script for ReportFlow — one installer, three executables + NSSM service.
; Compile with: ISCC.exe /DMyAppVersion=0.1.0 packaging\innosetup\reportflow.iss
; (CI passes the version; the default below is a fallback for local builds.)

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppName "ReportFlow"
#define MyServiceName "ReportFlow"
#define MyAppPublisher "ReportFlow"

[Setup]
AppId={{7F3C6A20-9B4E-4E2A-9C1D-REPORTFLOW01}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Show the welcome page so upgrades can state which version -> which version (see [Code]).
DisableWelcomePage=no
OutputBaseFilename=ReportFlow-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
SetupIconFile=..\..\assets\reportflow.ico
UninstallDisplayIcon={app}\ui\reportflow-ui.exe

[Files]
Source: "..\..\dist\worker\*";  DestDir: "{app}\worker";  Flags: recursesubdirs ignoreversion
Source: "..\..\dist\service\*"; DestDir: "{app}\service"; Flags: recursesubdirs ignoreversion
Source: "..\..\dist\ui\*";      DestDir: "{app}\ui";      Flags: recursesubdirs ignoreversion
Source: "..\nssm\nssm.exe";     DestDir: "{app}\nssm";    Flags: ignoreversion

[Dirs]
; ProgramData tree, writable by interactive users AND the LocalSystem service.
Name: "{commonappdata}\ReportFlow";              Permissions: users-modify
Name: "{commonappdata}\ReportFlow\config";       Permissions: users-modify
Name: "{commonappdata}\ReportFlow\logs";         Permissions: users-modify
Name: "{commonappdata}\ReportFlow\logs\service"; Permissions: users-modify
Name: "{commonappdata}\ReportFlow\state";        Permissions: users-modify
Name: "{commonappdata}\ReportFlow\runs";         Permissions: users-modify
Name: "{commonappdata}\ReportFlow\templates";    Permissions: users-modify
; Excel COM automation under LocalSystem (how the service runs) fails until these
; systemprofile Desktop folders exist — a long-standing Office/session-0 quirk.
Name: "{win}\System32\config\systemprofile\Desktop"; Check: IsWin64
Name: "{win}\SysWOW64\config\systemprofile\Desktop"; Check: IsWin64
Name: "{win}\System32\config\systemprofile\Desktop"; Check: not IsWin64

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Icons]
Name: "{group}\ReportFlow";           Filename: "{app}\ui\reportflow-ui.exe"
Name: "{group}\Uninstall ReportFlow"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ReportFlow";     Filename: "{app}\ui\reportflow-ui.exe"; Tasks: desktopicon

[Run]
; Register (or reconfigure) the NSSM-hosted service, then start it.
Filename: "{app}\nssm\nssm.exe"; Parameters: "install {#MyServiceName} ""{app}\service\reportflow-service.exe"""; Flags: runhidden; Check: ServiceNotInstalled
Filename: "{app}\nssm\nssm.exe"; Parameters: "set {#MyServiceName} AppDirectory ""{app}\service"""; Flags: runhidden
Filename: "{app}\nssm\nssm.exe"; Parameters: "set {#MyServiceName} AppStdout ""{commonappdata}\ReportFlow\logs\service\nssm_stdout.log"""; Flags: runhidden
Filename: "{app}\nssm\nssm.exe"; Parameters: "set {#MyServiceName} AppStderr ""{commonappdata}\ReportFlow\logs\service\nssm_stdout.log"""; Flags: runhidden
Filename: "{app}\nssm\nssm.exe"; Parameters: "set {#MyServiceName} AppRotateFiles 1"; Flags: runhidden
Filename: "{app}\nssm\nssm.exe"; Parameters: "set {#MyServiceName} AppRotateBytes 10485760"; Flags: runhidden
Filename: "{app}\nssm\nssm.exe"; Parameters: "set {#MyServiceName} Start SERVICE_AUTO_START"; Flags: runhidden
; When the admin supplied a service account, run the service (and its Excel workers) as that
; user so VSTO/Windows-auth add-ins like PI DataLink load. NSSM also grants the logon right.
Filename: "{app}\nssm\nssm.exe"; Parameters: "{code:NssmObjectNameArgs}"; Flags: runhidden; Check: HasServiceAccount
Filename: "{app}\nssm\nssm.exe"; Parameters: "start {#MyServiceName}"; Flags: runhidden
; Reopen the app after a silent update (the in-app updater closes it), and offer a
; "Launch ReportFlow" checkbox after an interactive install.
Filename: "{app}\ui\reportflow-ui.exe"; Flags: nowait skipifsilent postinstall; Description: "Launch {#MyAppName}"
Filename: "{app}\ui\reportflow-ui.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{app}\nssm\nssm.exe"; Parameters: "stop {#MyServiceName}"; Flags: runhidden; RunOnceId: "StopSvc"
Filename: "{app}\nssm\nssm.exe"; Parameters: "remove {#MyServiceName} confirm"; Flags: runhidden; RunOnceId: "RemoveSvc"

[UninstallDelete]
; Program files only. ProgramData (config/logs/state) is intentionally preserved.
Type: filesandordirs; Name: "{app}"

[Code]
var
  AccountPage: TInputQueryWizardPage;

function GetOldVersion: String;
var
  v: String;
begin
  // DisplayVersion of the currently-installed build (Inno's uninstall key for this AppId).
  Result := '';
  if RegQueryStringValue(HKLM,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7F3C6A20-9B4E-4E2A-9C1D-REPORTFLOW01}_is1',
    'DisplayVersion', v) then
    Result := v
  else if RegQueryStringValue(HKLM32,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7F3C6A20-9B4E-4E2A-9C1D-REPORTFLOW01}_is1',
    'DisplayVersion', v) then
    Result := v;
end;

procedure InitializeWizard;
var
  Old: String;
begin
  // On an upgrade, tell the user exactly which version -> which version on the welcome page.
  Old := GetOldVersion;
  if (Old <> '') and (Old <> '{#MyAppVersion}') then
    WizardForm.WelcomeLabel2.Caption :=
      'This will update {#MyAppName} from version ' + Old + ' to {#MyAppVersion}.' +
      ' Your jobs, settings, and logs are preserved.' + #13#10#13#10 +
      WizardForm.WelcomeLabel2.Caption;

  // Optional service log-on account. VSTO / Windows-integrated add-ins such as PI DataLink
  // cannot load under LocalSystem, so offer to run the service as a real PI-enabled user.
  AccountPage := CreateInputQueryPage(wpSelectTasks,
    'Service account',
    'Which Windows account should run ReportFlow?',
    'PI DataLink and other Excel add-ins only load under a real user account that has the ' +
    'add-in installed and data access — NOT LocalSystem. Enter such an account to run the ' +
    'service as that user, or leave both fields blank to keep LocalSystem (add-ins that ' +
    'need a user profile will not work).');
  AccountPage.Add('User (DOMAIN\user or .\user):', False);
  AccountPage.Add('Password:', True);
end;

function HasServiceAccount: Boolean;
begin
  Result := Trim(AccountPage.Values[0]) <> '';
end;

function NssmObjectNameArgs(Param: String): String;
begin
  // {code:...} scripted constants must take one String param. Quote both fields so spaces/
  // special characters survive; NSSM grants SeServiceLogonRight when setting ObjectName.
  Result := 'set {#MyServiceName} ObjectName "' + Trim(AccountPage.Values[0]) + '" "' +
    AccountPage.Values[1] + '"';
end;

function ServiceExists: Boolean;
var
  ResultCode: Integer;
begin
  // `sc query` returns 0 when the service exists.
  Result := Exec(ExpandConstant('{sys}\sc.exe'), 'query {#MyServiceName}',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function ServiceNotInstalled: Boolean;
begin
  Result := not ServiceExists;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Nssm: String;
begin
  // Upgrade path: stop the running service before we overwrite the executables so files
  // aren't locked. ProgramData is left untouched.
  Nssm := ExpandConstant('{app}\nssm\nssm.exe');
  if FileExists(Nssm) then
    Exec(Nssm, 'stop {#MyServiceName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // Kill ANY stray ReportFlow processes (old dev runs, zombies): a stray service exe
  // holding port 8787 silently blocks the freshly installed service from binding, and a
  // running UI locks its own files.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM reportflow-worker.exe /T',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM reportflow-service.exe /T',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM reportflow-ui.exe /T',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
