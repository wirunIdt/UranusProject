#!/bin/bash
cd "$(dirname "$0")"
echo ""
echo " ╔══════════════════════════════════╗"
echo " ║  🦾  Aria AI Assistant  v4.0.0  ║"
echo " ╚══════════════════════════════════╝"
echo ""

# Check Python
command -v python3 &>/dev/null || { echo "[ERROR] Python3 not found"; exit 1; }

# Install Flask if missing
python3 -c "import flask" 2>/dev/null || {
  echo "[SETUP] Installing Flask..."
  pip3 install flask requests edge-tts pyttsx3 pdfplumber
}

echo "[INFO] Starting server at http://localhost:7860"
echo "[INFO] Press Ctrl+C to stop"
echo ""
python3 server.py
