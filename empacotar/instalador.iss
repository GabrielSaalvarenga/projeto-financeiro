; Instalador do Windows (Inno Setup 6). Gerado pelo GitHub Actions; à mão, depois do PyInstaller:
;   iscc /DVersao=0.9.0 empacotar\instalador.iss
; Instala só para o usuário atual (não pede senha de administrador) e cria atalhos no Menu Iniciar.
; Os dados NÃO ficam aqui: ficam em %APPDATA%\Painel Financeiro e sobrevivem a desinstalar/atualizar.

#ifndef Versao
  #define Versao "0.0.0"
#endif

[Setup]
AppId={{6B1F3E2A-5C4D-4E8F-9A7B-2D1C0E9F8A11}
AppName=Painel Financeiro
AppVersion={#Versao}
AppPublisher=Projeto Financeiro
AppPublisherURL=https://github.com/GabrielSaalvarenga/projeto-financeiro
DefaultDirName={localappdata}\Programs\Painel Financeiro
DefaultGroupName=Painel Financeiro
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PainelFinanceiro-{#Versao}-Windows-Instalador
SetupIconFile=icone.ico
UninstallDisplayIcon={app}\Painel Financeiro.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\Painel Financeiro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; atualização: tira os arquivos da versão anterior (os dados ficam em %APPDATA% e não são tocados)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Painel Financeiro"; Filename: "{app}\Painel Financeiro.exe"
Name: "{group}\Pasta dos meus dados"; Filename: "{userappdata}\Painel Financeiro"
Name: "{autodesktop}\Painel Financeiro"; Filename: "{app}\Painel Financeiro.exe"; Tasks: desktopicon

[Dirs]
Name: "{userappdata}\Painel Financeiro"; Flags: uninsneveruninstall

[Run]
Filename: "{app}\Painel Financeiro.exe"; Description: "Abrir o Painel Financeiro"; Flags: nowait postinstall skipifsilent
