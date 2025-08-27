@echo off
if exist dist\Glass (
  start "" ".\dist\Glass"
) else (
  echo dist\Glass not found. Build first.
)
