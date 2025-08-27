@echo off
setlocal
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist
call build.bat
