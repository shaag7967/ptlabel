@echo off
rem Startet PT-Label unter Windows. Beim ersten Start wird die Python-Umgebung eingerichtet.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Richte Python-Umgebung ein ...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)
start "" ".venv\Scripts\pythonw.exe" -m ptlabel %*
exit /b 0

:error
echo Einrichtung fehlgeschlagen. Ist Python 3.10 oder neuer installiert?
pause
exit /b 1
