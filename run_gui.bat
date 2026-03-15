@echo off
chcp 65001 >nul
call .venv\Scripts\activate.bat
aletheia-gui
