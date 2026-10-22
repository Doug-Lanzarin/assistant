@echo off
rem ==========================================================================
rem  JARVIS - configuracao inicial (Windows 10/11)
rem  Uso: dois cliques, ou no terminal:  setup.bat [-NoVoice] [-WhatsApp]
rem       [-Ollama] [-Tests] [-Force] [-Offline] [-Yes]
rem  Pode ser executado de novo a qualquer momento: so faz o que falta.
rem  Toda a logica fica em scripts\setup.ps1 e scripts\jarvis_setup.py.
rem ==========================================================================
setlocal EnableExtensions DisableDelayedExpansion
title JARVIS - configuracao
cd /d "%~dp0"
if not exist "%~dp0scripts\jarvisctl.py" goto :nodir

set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"
"%PS%" -NoLogo -NoProfile -Command "exit 0" >nul 2>&1
if errorlevel 1 goto :nops

rem ExecutionPolicy Bypass vale SO para este processo; a politica do sistema nao muda.
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" %*
set "RC=%ERRORLEVEL%"

rem Confirmacao independente: so considera concluido se o proprio JARVIS confirmar.
if not "%RC%"=="0" goto :report
if not exist "%~dp0backend\.venv\Scripts\python.exe" (set "RC=1" & goto :report)
"%~dp0backend\.venv\Scripts\python.exe" "%~dp0scripts\jarvisctl.py" setup-status
if errorlevel 1 set "RC=1"

:report
echo.
if "%RC%"=="0" (
  echo  Configuracao concluida. Para iniciar o JARVIS, de dois cliques em start.bat.
) else (
  echo  A configuracao NAO foi concluida - codigo %RC%.
  echo  Corrija os itens marcados com FALHA acima e execute setup.bat novamente.
  echo  O relatorio completo fica em data\logs\setup-*.log
)
goto :end

:nodir
echo [FALHA] Pasta do JARVIS incompleta ou inacessivel: "%~dp0"
echo         Falta scripts\jarvisctl.py - baixe o projeto completo novamente.
set "RC=1"
goto :end

:nops
echo [FALHA] O Windows PowerShell nao esta disponivel.
echo         Ele faz parte do Windows 10/11; verifique se nao foi removido ou bloqueado.
set "RC=1"
goto :end

:end
rem Aberto com dois cliques (cmd.exe /c ...)? Mantem a janela aberta.
rem Expansao atrasada: caminhos com & ou parenteses nao quebram o teste.
setlocal EnableDelayedExpansion
set "CL=!CMDCMDLINE!"
if defined CL set "CL=!CL:"=!"
if defined CL if /i not "!CL:/c =!"=="!CL!" pause
endlocal
endlocal & exit /b %RC%
