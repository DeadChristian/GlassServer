@echo off
setlocal
set NAME=Glass
set VERSION=%1
if "%VERSION%"=="" (
  set /p VERSION=Enter version (e.g., 1.0.0): 
)
if not exist "dist\%NAME%" (
  echo dist\%NAME% not found. Run rebuild.cmd first.
  pause & exit /b 1
)
set DEST=releases\%NAME%_v%VERSION%
if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%DEST%"
xcopy /e /i /y "dist\%NAME%" "%DEST%\" >nul
for %%F in (README.md README.txt EULA.txt LICENSE.txt) do if exist "%%F" copy /y "%%F" "%DEST%\" >nul
echo Release ready at %DEST%
echo (Zip and upload this folder to Gumroad.)
pause
