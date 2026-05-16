@echo off
title Aria Discord Bot
color 0A
cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════════╗
echo  ║  🤖  Aria Discord Bot               ║
echo  ╚══════════════════════════════════════╝
echo.

python --version >nul 2>&1
if errorlevel 1 (echo [ERROR] Python not found. & pause & exit)

pip show discord.py >nul 2>&1
if errorlevel 1 (
  echo [SETUP] Installing discord.py + aiohttp...
  pip install "discord.py>=2.3.0" aiohttp
)

echo [INFO] Make sure Aria server is running first:
echo [INFO]   python server.py
echo.
echo [INFO] Set your Discord token:
echo [INFO]   Either in config.json: "discord_token": "YOUR_TOKEN"
echo [INFO]   Or env: set DISCORD_TOKEN=YOUR_TOKEN
echo.

if "%DISCORD_TOKEN%"=="" (
  set /p DISCORD_TOKEN=[INPUT] Paste your Discord Bot Token: 
)

python discord_bot.py
pause
