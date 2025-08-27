@echo off
setlocal
cd /d %~dp0

echo Cleaning...
if exist build rd /s /q build
if exist dist rd /s /q dist
del /q *.spec 2>nul

echo Building...
py -m PyInstaller ^
  --log-level=WARN ^
  --onedir ^
  --name Glass ^
  --paths src ^
  --windowed ^
  --clean ^
  --noupx ^
  --icon src\assets\icon.ico ^
  --add-data "src\assets;assets" ^
  src\main_gui.py

if errorlevel 1 (
  echo Retrying with console logs...
  py -m PyInstaller ^
    --log-level=DEBUG ^
    --onedir ^
    --name Glass ^
    --paths src ^
    --console ^
    --clean ^
    --noupx ^
    --icon src\assets\icon.ico ^
    --add-data "src\assets;assets" ^
    src\main_gui.py
)
endlocal
