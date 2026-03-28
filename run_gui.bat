@echo off
chcp 65001 >nul
cd /d "%~dp0"

taskkill /IM aletheia-gui.exe /F >nul 2>&1

echo [Step 1] Python works?
.venv\Scripts\python.exe -c "print('OK')"
echo.

echo [Step 2] Gradio import?
.venv\Scripts\python.exe -c "import gradio; print('Gradio', gradio.__version__)"
echo.

echo [Step 3] Aletheia import?
.venv\Scripts\python.exe -c "from aletheia import gui; print('Import OK')"
echo.

echo [Step 4] Launching...
.venv\Scripts\python.exe -m aletheia.gui
echo.
echo [Exit code: %errorlevel%]
pause
