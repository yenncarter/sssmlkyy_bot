@echo off
REM Stop beauty_bot instances in THIS folder only (no pause)
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

powershell -NoProfile -Command ^
  "$root = '%ROOT%';" ^
  "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {" ^
  "  $_.CommandLine -like '*main.py*' -and (" ^
  "    ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($root)) -or" ^
  "    ($_.CommandLine -like ('*' + $root + '*'))" ^
  "  )" ^
  "} | ForEach-Object { Write-Host ('Stopping PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

if exist "%ROOT%\.bot.pid" del /f /q "%ROOT%\.bot.pid"
