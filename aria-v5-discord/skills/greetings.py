"""
Greeting messages based on time of day
"""
from datetime import datetime

GREETINGS = {
    "en": {
        "morning":   "Good morning! ☀️ I'm Aria, your personal AI assistant. Ready to help!",
        "afternoon": "Good afternoon! 🌤️ I'm Aria, your AI assistant. What can I do for you?",
        "evening":   "Good evening! 🌆 I'm Aria. How may I assist you today?",
        "night":     "Working late? 🌙 I'm Aria — still here to help, no matter the hour!",
    },
    "th": {
        "morning":   "สวัสดีตอนเช้าครับ! ☀️ ผมชื่อ Aria ผู้ช่วย AI ส่วนตัวของคุณ พร้อมช่วยงานแล้ว!",
        "afternoon": "สวัสดีตอนบ่ายครับ! 🌤️ ผม Aria มีอะไรให้ช่วยไหมครับ?",
        "evening":   "สวัสดีตอนเย็นครับ! 🌆 ผม Aria วันนี้เป็นอย่างไรบ้าง?",
        "night":     "ดึกแล้วยังทำงานอยู่เหรอ? 🌙 ผม Aria ยังตื่นอยู่เสมอนะครับ!",
    },
}

def get_period() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"

def get_greeting(lang: str = "th") -> str:
    period = get_period()
    return GREETINGS.get(lang, GREETINGS["th"]).get(period, "Hello! I'm Aria 🦾")
