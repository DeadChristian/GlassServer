@echo off
setlocal

REM Ensure we're in the project root
if not exist src\ (
  echo Run this in the folder that contains src^\
  pause
  exit /b 1
)

echo Cleaning extras (won't touch src\core or src\assets)...

REM --- Known prototype/old files under src\ (safe to remove)
for %%F in (
  wire_globe.py
  theme_phosphor.py
  first_run_py.py
  hotkeys.py
  licensing.py
  main_api.py
  memory.py
  ui_hooks.py
  window_manager.py
) do (
  if exist "src\%%F" del /q "src\%%F"
)

REM Stray notepad file
if exist "src\New Text Document.txt" del /q "src\New Text Document.txt"

REM Backup/caches
del /s /q "src\*.bak*"  2>nul
del /s /q "src\*.pyc"   2>nul
for /d /r %%D in (__pycache__) do rd /s /q "%%D"

REM Build artifacts
if exist build       rmdir /s /q build
if exist dist        rmdir /s /q dist
if exist build_tmp   rmdir /s /q build_tmp
if exist pyi_build.log del /q pyi_build.log

REM Optional leftover zips in root (you said no zips)
for %%Z in (*.zip) do if exist "%%Z" del /q "%%Z"

echo.
echo Done. Kept only the minimal set:
echo   src\main_gui.py  src\globe_widget.py  src\theme.py  src\paths.py  src\net.py  src\hwid.py
echo   src\assets\*     src\core\*           build.bat     run_dev.cmd   rebuild.cmd
echo   open_dist.cmd    clean_build_artifacts.cmd  README.md  .gitignore
pause
