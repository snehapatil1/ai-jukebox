@echo off
REM Launch AI Jukebox - Gradio App
REM Serves on http://127.0.0.1:7860

cd /d "%~dp0"

REM Activate the local virtual environment
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM Reuse a healthy existing instance; otherwise start and wait for readiness.
if not exist ".venv\Scripts\python.exe" (
    echo Missing project Python environment. See README.md for setup.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" launcher.py
if errorlevel 1 (
    echo Could not open AI Jukebox. Review the error above.
    pause
)
