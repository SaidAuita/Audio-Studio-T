@echo off
setlocal

echo ========================================================
echo   Audio Studio T (NiceGUI + Fish Audio Drama 3)
echo ========================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not exist "python\python.exe" (
    echo ERROR: Python not found. Check python junction or folder.
    pause
    exit /b 1
)

if not exist "app.py" (
    echo ERROR: app.py not found.
    pause
    exit /b 1
)

set "TEMP=%SCRIPT_DIR%temp"
set "TMP=%SCRIPT_DIR%temp"
if not exist "%TEMP%" mkdir "%TEMP%"

set "HF_HOME=%SCRIPT_DIR%models"
set "HUGGINGFACE_HUB_CACHE=%SCRIPT_DIR%models\hub"
set "HF_HUB_CACHE=%SCRIPT_DIR%models\hub"
set "TRANSFORMERS_CACHE=%SCRIPT_DIR%models"
set "TORCH_HOME=%SCRIPT_DIR%models\torch"

set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

echo Starting Audio Studio T web server...
echo Server URL: http://127.0.0.1:7860
python\python.exe app.py

if errorlevel 1 (
    echo.
    echo ERROR: Application stopped with an error.
    pause
    exit /b 1
)
pause
