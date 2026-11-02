@echo off
rem Launch the local reader as a standalone app window (no address bar).
setlocal
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files\Microsoft\Edge\Application\msedge.exe"
if not exist "%CHROME%" (
  echo Browser not found. Open web\index.html manually.
  pause
  exit /b 1
)

set "PAGE=file:///%~dp0index.html"
set "PAGE=%PAGE:\=/%"
set "PROFILE=%LOCALAPPDATA%\Temp\kbdoc-profile"

start "" "%CHROME%" --app="%PAGE%" --user-data-dir="%PROFILE%" ^
 --no-first-run --no-default-browser-check --disable-features=Translate ^
 --allow-file-access-from-files --window-size=580,860
