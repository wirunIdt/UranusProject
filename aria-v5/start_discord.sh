#!/bin/bash
cd "$(dirname "$0")"
echo ""
echo " ╔══════════════════════════════════════╗"
echo " ║  🤖  Aria Discord Bot               ║"
echo " ╚══════════════════════════════════════╝"

python3 -c "import discord" 2>/dev/null || pip3 install "discord.py>=2.3.0" aiohttp

echo ""
echo "[INFO] Make sure Aria server is running: python3 server.py"
echo "[INFO] Set token: export DISCORD_TOKEN=your_token"
echo ""

python3 discord_bot.py
