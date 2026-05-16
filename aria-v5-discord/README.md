# 🦾 Aria AI Assistant v4 — Full Local Stack

รวม Python backend + Web UI ไว้ในที่เดียว
รัน local ผ่าน browser — ใช้งานได้ทั้ง Desktop + Mobile

---

## 🚀 Quick Start

### 1. ติดตั้ง Ollama + model
```bash
# Download: https://ollama.ai
ollama serve
ollama pull qwen2.5:7b
```

### 2. รัน Aria
```bash
# Windows
start.bat

# macOS / Linux
bash start.sh

# Manual
pip install -r requirements.txt
python server.py
```

### 3. เปิด browser
```
http://localhost:7860
```
> หน้าต่าง browser จะเปิดให้อัตโนมัติ!

---

## 📡 API Endpoints

| Endpoint | Method | หน้าที่ |
|---|---|---|
| `GET /` | GET | Web UI |
| `/api/status` | GET | ตรวจสอบ Ollama + system info |
| `/api/chat` | POST | Streaming chat (SSE) |
| `/api/volume` | POST | ควบคุมเสียง system จริง |
| `/api/weather` | GET | ข้อมูลสภาพอากาศ |
| `/api/models` | GET | รายชื่อ Ollama models |
| `/api/switch_model` | POST | เปลี่ยน model |
| `/api/read_file` | POST | อ่านไฟล์ (PDF, image, text) |
| `/api/stt` | POST | Speech-to-Text (offline Whisper) |
| `/api/command` | POST | System commands (เปิด/ปิดแอพ) |
| `/api/config` | GET/POST | บันทึก/โหลดการตั้งค่า |
| `/api/history` | GET | ประวัติ sessions |
| `/api/clear_chat` | POST | ล้าง chat history |

---

## ✨ Features

| Feature | ทำงานอย่างไร |
|---|---|
| 💬 **Streaming Chat** | SSE stream จาก Ollama → browser real-time |
| 🌤️ **Weather** | Open-Meteo API (ฟรี, ไม่ต้อง API key) |
| 🔊 **System Volume** | pycaw (Win) / osascript (Mac) / pactl (Linux) |
| 🎙️ **Neural TTS** | edge-tts (Microsoft Neural voices) |
| 🎤 **STT** | Web Speech API (browser) + faster-whisper (offline) |
| 📎 **File Upload** | PDF, images, code files → AI อ่านได้ |
| 📋 **History** | บันทึก SQLite อัตโนมัติทุก session |
| 🌐 **Mobile** | Responsive design, เปิดจากมือถือได้ |
| 🌙☀️ **Theme** | Dark / Light switch |
| 🇹🇭🇺🇸 **Language** | TH / EN switch |

---

## ⌨️ Keyboard Shortcuts

| Key | Action |
|---|---|
| `Enter` | Send message |
| `Ctrl+↑` | Volume Up (+10%) |
| `Ctrl+↓` | Volume Down (-10%) |
| `Ctrl+M` | Toggle Mute |

---

## 💬 Voice / System Commands

```
open chrome          / เปิด chrome
open youtube         / เปิด youtube
volume up            / เพิ่มเสียง
volume down          / ลดเสียง
mute                 / ปิดเสียง
อากาศวันนี้ Bangkok  → Weather card
weather in Tokyo     → Weather card
```

---

## 📁 Structure

```
aria-v4/
├── server.py            ← Flask server (main entry)
├── start.bat / start.sh ← One-click launcher
├── requirements.txt
├── config.json          ← Auto-created on first run
├── history.db           ← SQLite chat history
├── logs/                ← Session exports
├── ui/
│   └── index.html       ← Full Web/Mobile UI
├── agent/
│   └── core.py          ← Ollama streaming
├── skills/
│   ├── system_control.py  ← Open apps, URLs, volume
│   ├── volume_control.py  ← Real system volume API
│   ├── weather.py         ← Open-Meteo weather
│   ├── natural_tts.py     ← edge-tts neural voices
│   ├── voice.py           ← STT (Whisper + Google)
│   ├── recorder.py        ← SQLite chat recorder
│   └── file_reader.py     ← PDF/image/text reader
└── config/
    └── settings.py
```

---

## 🔧 Recommended Models (4060 Laptop 8GB VRAM)

| Model | Speed | Best For |
|---|---|---|
| `qwen2.5:7b` | ⚡⚡⚡ | General use (default) |
| `qwen2.5-coder:7b` | ⚡⚡⚡ | Coding |
| `mistral:7b` | ⚡⚡⚡⚡ | English, fast |
| `llama3.2:3b` | ⚡⚡⚡⚡⚡ | Fastest |
