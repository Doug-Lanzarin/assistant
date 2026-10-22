@echo off
rem ==========================================================================
rem  JARVIS - iniciar (depois do setup.bat)
rem  Uso: dois cliques, ou no terminal:  start.bat [--no-browser] [--no-agent]
rem       [--whatsapp-web]
rem  Encerrar: Ctrl+C nesta janela (ou feche a janela).
rem  Nao instala nada e nao apaga dados.
rem ==========================================================================
setlocal EnableExtensions DisableDelayedExpansion
title JARVIS
cd /d "%~dp0"
if not exist "%~dp0scripts\jarvisctl.py" goto :nodir

set "VENV=%~dp0backend\.venv"
if not exist "%VENV%\Scripts\python.exe" goto :nosetup
if not exist "%VENV%\Scripts\activate.bat" goto :nosetup
call "%VENV%\Scripts\activate.bat"

rem Logs do backend e do agente tambem no terminal (e sempre em data\logs).
set "JARVIS_LOG_CONSOLE=1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem jarvisctl run: verifica a configuracao, carrega o .env, checa a porta,
rem evita instancias duplicadas, inicia backend + interface + agente e
rem encerra todos ao receber Ctrl+C.
"%VENV%\Scripts\python.exe" "%~dp0scripts\jarvisctl.py" run %*
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" goto :end
echo.
echo  O JARVIS encerrou com erro - codigo %RC%.
echo  Veja as mensagens acima e os logs em data\logs\ - jarvis.log, supervisor.log, agent.log
goto :end

:nosetup
echo [FALHA] O JARVIS ainda nao foi configurado neste computador.
echo         Execute setup.bat primeiro - dois cliques - e depois start.bat.
set "RC=1"
goto :end

:nodir
echo [FALHA] Pasta do JARVIS incompleta ou inacessivel: "%~dp0"
echo         Falta scripts\jarvisctl.py - baixe o projeto completo novamente.
set "RC=1"
goto :end

:end
if "%RC%"=="0" goto :done
rem Aberto com dois cliques (cmd.exe /c ...)? Em caso de erro, mantem a janela aberta.
rem Expansao atrasada: caminhos com & ou parenteses nao quebram o teste.
setlocal EnableDelayedExpansion
set "CL=!CMDCMDLINE!"
if defined CL set "CL=!CL:"=!"
if defined CL if /i not "!CL:/c =!"=="!CL!" pause
endlocal
:done
endlocal & exit /b %RC%
