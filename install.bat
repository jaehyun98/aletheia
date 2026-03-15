@echo off
chcp 65001 >nul
echo ============================================
echo  Aletheia - Install
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org
    pause
    exit /b 1
)

:: Create venv
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

:: Activate and install
echo Installing dependencies...
call .venv\Scripts\activate.bat
pip install -e . --quiet

:: Copy config if not exists
if not exist "config.yaml" (
    echo Creating config.yaml from template...
    copy config.example.yaml config.yaml >nul
)

echo.
echo ============================================
echo  Install complete!
echo.
echo  Prerequisites:
echo    - Ollama: https://ollama.com (download and run)
echo    - Run: ollama pull qwen2.5:7b
echo.
echo  Launch:
echo    run_gui.bat
echo ============================================
pause
