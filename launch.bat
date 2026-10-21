@echo off
REM Launch AI Jukebox - Gradio App
REM Serves on http://127.0.0.1:7860

cd /d "%~dp0"

REM Activate the local virtual environment
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM Start the app in headless mode with a delayed browser open
start "" /b python app.py --server.port 7860 --server.headless true --server.autorun false
timeout /t 12 >nul
start http://127.0.0.1:7860
