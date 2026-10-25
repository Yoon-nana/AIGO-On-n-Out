@echo off
setlocal
if not exist "%~dp0AIGO_Launch.ps1" goto missing
if not exist "%~dp0AIGO_Install.ps1" goto missing
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0AIGO_Launch.ps1"
set "AIGO_EXIT=%ERRORLEVEL%"
if not "%AIGO_EXIT%"=="0" pause
exit /b %AIGO_EXIT%
:missing
echo [AIGO] AIGO_Launch.ps1 or AIGO_Install.ps1 was not found beside this CMD file.
echo Right-click the ZIP, choose Extract All, and run this file from the extracted folder.
echo Download the complete ZIP again if a PS1 file is still missing.
pause
exit /b 1
