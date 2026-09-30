@echo off
rem Lance Horizon depuis ce depot avec son environnement virtuel (.venv), sans console.
rem Au premier lancement, cree le .venv et y installe Horizon en mode editable.
setlocal
set "REPO=%~dp0"
set "VENV=%REPO%.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"

cd /d "%REPO%"

if not exist "%PY%" (
    echo Creation de l'environnement virtuel dans "%VENV%"...
    python -m venv "%VENV%" || goto :error
)

rem Reinstalle si le paquet horizon du venv est absent ou pointe vers un autre depot.
"%PY%" -c "import horizon, pathlib, sys; sys.exit(0 if pathlib.Path(horizon.__file__).resolve().is_relative_to(pathlib.Path(r'%REPO%src').resolve()) else 1)" >nul 2>&1
if errorlevel 1 (
    echo Installation de Horizon dans l'environnement virtuel...
    "%PY%" -m pip install -e "%REPO%." || goto :error
)

start "" "%PYW%" -m horizon %*
exit /b 0

:error
echo Echec de la preparation de l'environnement virtuel.
pause
exit /b 1
