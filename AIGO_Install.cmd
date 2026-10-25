@echo off
setlocal
if not exist "%~dp0AIGO_Install.ps1" goto missing
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0AIGO_Install.ps1"
set "AIGO_EXIT=%ERRORLEVEL%"
pause
exit /b %AIGO_EXIT%
:missing
echo [AIGO] AIGO_Install.ps1 was not found beside this CMD file.
echo Right-click the ZIP, choose Extract All, and run this file from the extracted folder.
echo Download the complete ZIP again if the PS1 file is still missing.
pause
exit /b 1
