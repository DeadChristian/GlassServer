@echo off
setlocal ENABLEDELAYEDEXPANSION

REM --- Sanity check ---
if not exist "src\" (
  echo This script must be run in the folder that contains src^\
  pause
  exit /b 1
)

echo.
echo === Moving UI files out of core -> src =====================================

for %%F in (main_gui.py globe_widget.py theme.py paths.py net.py hwid.py) do (
  if exist "src\core\%%F" (
    echo move src\core\%%F -> src\
    move /y "src\core\%%F" "src\" >nul
  )
)

REM --- Ensure assets folder exists ---
if not exist "src\assets" mkdir "src\assets"

echo.
echo === Moving build/.cmd files from src -> project root ========================

for %%F in (build.bat run_dev.cmd rebuild.cmd open_dist.cmd clean_build_artifacts.cmd README.md README.txt) do (
  if exist "src\%%F" (
    echo move src\%%F -> .\
    move /y "src\%%F" ".\" >nul
  )
)

echo.
echo === Cleaning caches and build artifacts ====================================

REM Py caches
for /d /r %%D in (__pycache__) do rd /s /q "%%D" 2>nul
del /s /q "src\*.pyc" 2>nul

REM Build output
for %%D in (build dist out build_tmp) do (
  if exist "%%D" (
    echo delete %%D\
    rmdir /s /q "%%D"
  )
)
if exist "pyi_build.log" del /q "pyi_build.log"

echo.
echo === Removing old/unused root files (safe) ==================================

for %%F in (main.py glass_legacy.py diag_imports.py) do (
  if exist "%%F" (
    echo delete %%F
    del /q "%%F"
  )
)

REM Optional cleanups (uncomment if you don't need these)
REM del /q "Glass.spec"  2>nul
REM del /q ".env.example" 2>nul
REM del /q "disclaimer_accepted.txt" 2>nul
REM del /q "EULA.txt" 2>nul

echo.
echo === Keeping core logic only in src\core ====================================
echo (should contain: __init__.py, settings.py, transparency.py, window_utils.py)

echo.
echo Done.
echo.
echo Expected tree:
echo   src\main_gui.py  src\globe_widget.py  src\theme.py  src\paths.py  src\net.py  src\hwid.py
echo   src\assets\*
echo   src\core\__init__.py  src\core\settings.py  src\core\transparency.py  src\core\window_utils.py
echo   build.bat  run_dev.cmd  rebuild.cmd  open_dist.cmd  clean_build_artifacts.cmd  README(.md)
echo.
pause
