@echo off
rem Runs one Claud pass (find, render, upload) and appends the output to data\claud.log.
rem Used by the daily scheduled task; you can also double-click it to run Claud once.
cd /d "%~dp0.."
echo ===== %date% %time% ===== >> "data\claud.log"
call ".venv\Scripts\claud.exe" run >> "data\claud.log" 2>&1
