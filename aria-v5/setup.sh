#!/bin/bash
# ARIA v5 — Quick Setup
pip install flask flask-cors flask-socketio psutil requests 2>/dev/null || \
pip install flask flask-cors psutil requests --break-system-packages
echo "Starting ARIA v5..."
python3 server.py
