@echo off
chcp 65001 >nul
cd /d "%~dp0"
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
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
)

:: Install using venv pip directly (no activate needed)
echo Installing dependencies...
.venv\Scripts\pip.exe install -e . --quiet
if errorlevel 1 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)

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
