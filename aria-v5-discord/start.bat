@echo off
title Aria AI v4
color 0A
cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════╗
echo  ║  🦾  Aria AI Assistant  v4.0.0  ║
echo  ╚══════════════════════════════════╝
echo.

python --version >nul 2>&1
if errorlevel 1 (echo [ERROR] Python not found. & pause & exit)

pip show flask >nul 2>&1
if errorlevel 1 (
  echo [SETUP] Installing dependencies...
  pip install flask requests edge-tts pyttsx3 pdfplumber
)

echo [INFO] Starting server at http://localhost:7860
echo [INFO] Press Ctrl+C to stop
echo.
python server.py
pause
