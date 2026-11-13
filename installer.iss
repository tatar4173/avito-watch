#define AppName "Avito Watch"
#define AppVersion "1.0.1"
#define AppPublisher "tatar4173"

[Setup]
AppId={{7C4E2B51-9D3A-4F62-8B1E-2A6D5C9E4F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppComments=Монитор выдачи Avito
DefaultDirName={localappdata}\Programs\Avito Watch
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=AvitoWatch-setup-{#AppVersion}
SetupIconFile=avito-watch.ico
UninstallDisplayIcon={app}\avito-watch.ico
Compression=zip
SolidCompression=no
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
ShowLanguageDialog=no
CloseApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "deps"; Description: "Установить зависимости (playwright, psutil)"; GroupDescription: "Что поставить:"; Flags: checkedonce
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Что поставить:"; Flags: checkedonce
Name: "login"; Description: "Открыть окно входа в Avito после установки"; GroupDescription: "Что поставить:"; Flags: checkedonce

[Files]
Source: "avito_watch.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "app.pyw"; DestDir: "{app}"; Flags: ignoreversion
Source: "install_deps.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "avito-watch.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.example.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "ИНСТРУКЦИЯ.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "КРАТКО.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "запустить.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "войти-в-avito.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{code:GetPythonwExe}"; Parameters: """{app}\app.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\avito-watch.ico"
Name: "{group}\Инструкция"; Filename: "{app}\ИНСТРУКЦИЯ.txt"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{code:GetPythonwExe}"; Parameters: """{app}\app.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\avito-watch.ico"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_deps.ps1"" -Silent"; StatusMsg: "Устанавливаю зависимости: playwright и psutil..."; Flags: runhidden waituntilterminated; Tasks: deps
Filename: "{code:GetPythonwExe}"; Parameters: """{app}\avito_watch.py"" --login"; WorkingDir: "{app}"; Description: "Войти в Avito"; Flags: postinstall nowait skipifsilent; Tasks: login

[UninstallDelete]
Type: files; Name: "{app}\__pycache__\*"
Type: dirifempty; Name: "{app}\__pycache__"

[Code]
var
  PythonExe: String;
  PythonwExe: String;
  ChromeFound: Boolean;

function GetPythonwExe(Param: String): String;
begin
  if PythonwExe <> '' then
    Result := PythonwExe
  else
    Result := 'pythonw.exe';
end;

function ChromePresent(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{pf}\Google\Chrome\Application\chrome.exe')) or
    FileExists(ExpandConstant('{pf32}\Google\Chrome\Application\chrome.exe')) or
    FileExists(ExpandConstant('{localappdata}\Google\Chrome\Application\chrome.exe'));
end;

function FindPythonPath(): String;
var
  TempFile: String;
  Lines: TArrayOfString;
  Cmd: String;
  ResultCode: Integer;
begin
  Result := '';
  TempFile := ExpandConstant('{tmp}\python-path.txt');
  Cmd := ExpandConstant('{cmd}');
  if Exec(Cmd, '/c where python > "' + TempFile + '" 2>nul', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if LoadStringsFromFile(TempFile, Lines) then
      if GetArrayLength(Lines) > 0 then
        Result := Trim(Lines[0]);
  end;
end;

function InitializeSetup(): Boolean;
var
  Answer: Integer;
  Path: String;
  ResultCode: Integer;
begin
  Result := True;
  ChromeFound := ChromePresent();
  Path := FindPythonPath();
  if Path = '' then
  begin
    Answer := MsgBox('Python не найден.' + #13#10 +
      'Без Python 3.10+ программа не запустится.' + #13#10#13#10 +
      'Открыть страницу загрузки Python сейчас?', mbConfirmation, MB_YESNO);
    if Answer = IDYES then
      ShellExec('open', 'https://www.python.org/downloads/windows/', '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
    Result := False;
    Exit;
  end;
  PythonExe := Path;
  PythonwExe := Path;
  StringChangeEx(PythonwExe, 'python.exe', 'pythonw.exe', True);
  if not FileExists(PythonwExe) then
    PythonwExe := Path;

  if not ChromeFound then
  begin
    Answer := MsgBox('Google Chrome не найден.' + #13#10 +
      'Программа работает через настоящий Chrome, без него не запустится.' + #13#10#13#10 +
      'Продолжить установку?', mbConfirmation, MB_YESNO);
    Result := Answer = IDYES;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not FileExists(ExpandConstant('{app}\config.json')) then
      CopyFile(ExpandConstant('{app}\config.example.json'),
               ExpandConstant('{app}\config.json'), False);
  end;
end;
