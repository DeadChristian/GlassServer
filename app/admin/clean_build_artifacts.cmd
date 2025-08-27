@echo off
setlocal
if exist build       rmdir /s /q build
if exist dist        rmdir /s /q dist
if exist build_tmp   rmdir /s /q build_tmp
if exist pyi_build.log del /q pyi_build.log
echo Cleaned build artifacts.
