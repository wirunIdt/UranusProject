import json
import os

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings.json")

DEFAULT_SETTINGS = {
    "theme": "dark",
    "language": "th",
    "model": "qwen2.5:7b",
    "ollama_host": "http://localhost:11434",
    "voice_enabled": False,
    "tts_enabled": False,
    "assistant_name": "Aria",
    "user_name": "You",
    "window_geometry": "960x700",
}

def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_SETTINGS, **data}
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()

def save_settings(settings: dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Settings save error: {e}")
