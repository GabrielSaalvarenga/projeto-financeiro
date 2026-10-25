@echo off
rem Duplo clique no Windows: abre o Painel Financeiro. Ver README, "Jeito mais facil".
chcp 65001 >nul
cd /d "%~dp0"

set "PYCMD="
py -3.12 -c "pass" >nul 2>&1 && set "PYCMD=py -3.12"
if not defined PYCMD py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PYCMD=py -3"
if not defined PYCMD python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PYCMD=python"
if defined PYCMD goto run

echo.
echo [ERRO] Nao encontrei o Python 3.10 ou mais novo (o recomendado e o 3.12).
echo.
choice /c SN /m "Quer que eu tente instalar o Python 3.12 agora (usa o winget do Windows)"
if errorlevel 2 goto manual
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
echo.
echo Pronto. FECHE esta janela e de dois cliques em Iniciar.bat de novo.
pause
exit /b 0

:manual
echo Instale em https://www.python.org/downloads/ (marque "Add python.exe to PATH") e rode de novo.
start https://www.python.org/downloads/
pause
exit /b 1

:run
%PYCMD% iniciar.py
if errorlevel 1 pause
