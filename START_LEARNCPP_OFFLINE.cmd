@echo off
setlocal
cd /d "%~dp0"
set "PORT=8765"

where python >nul 2>nul
if %ERRORLEVEL%==0 goto run_python

where py >nul 2>nul
if %ERRORLEVEL%==0 goto run_py

echo Nie znaleziono Pythona (python/py) w PATH.
echo Zainstaluj Python i uruchom ten plik ponownie.
pause
exit /b 1

:run_python
start "" "http://127.0.0.1:%PORT%/www.learncpp.com/index.html"
python -m http.server %PORT%
exit /b %ERRORLEVEL%

:run_py
start "" "http://127.0.0.1:%PORT%/www.learncpp.com/index.html"
py -3 -m http.server %PORT%
exit /b %ERRORLEVEL%
