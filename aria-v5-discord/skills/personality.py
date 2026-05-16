"""
Human Personality Engine
- Jokes (Thai + English)
- Casual natural speech
- Emotional responses
- Random personality touches
"""
import random
from datetime import datetime

# ── Jokes database ─────────────────────────────────────────────────────────
JOKES_TH = [
    ("ทำไมโปรแกรมเมอร์ถึงชอบ dark mode?", "เพราะ light attracts bugs! 🐛"),
    ("AI กับมนุษย์ต่างกันยังไง?", "มนุษย์ลืมได้ ผมลืมเป็นบางเวลา แต่ไม่เคยลืมว่าคุณชื่ออะไรเลย 😄"),
    ("ทำไม JavaScript ถึงน่ากลัว?", "เพราะ undefined is not a function... ตอน production! 😱"),
    ("Computer เป็นเพศอะไร?", "ผู้หญิง เพราะมี motherboard, no man understands her, และ memory เยอะมาก 😂"),
    ("ทำไม Git commit message มักจะสั้น?", "เพราะนักพัฒนาขี้เกียจอธิบายว่าทำไมถึง fix bug เดิมอีกแล้ว 😅"),
    ("รู้มั้ยว่า Stack Overflow คืออะไร?", "บ้านของโปรแกรมเมอร์ทุกคน และ error message ของเราทุกวัน 🏠"),
    ("ทำไม AI ถึงไม่เล่นหมากรุก?", "เพราะมันจริงจังเกินไป ไม่มีอารมณ์ขัน... อย่างฉัน! 😎"),
    ("Python vs JavaScript?", "Python อ่านง่ายเหมือนภาษาคน แต่ JavaScript... มันก็มีเสน่ห์นะ ถ้าคุณชอบความเจ็บปวด 😆"),
    ("นักพัฒนาตายไปไหน?", "ไปแก้ bug ใน production ก่อนนอน แล้วไม่ได้นอน 😴"),
    ("ทำไม AI ชอบเลข 0?", "เพราะทุกอย่างเริ่มจาก 0 รวมถึงความผิดพลาดของฉัน 😅"),
]

JOKES_EN = [
    ("Why do programmers prefer dark mode?", "Because light attracts bugs! 🐛"),
    ("Why did the AI break up with the database?", "Too many unresolved issues! 💔"),
    ("How many programmers does it take to change a light bulb?", "None, that's a hardware problem! 💡"),
    ("Why do Java developers wear glasses?", "Because they don't C#! 👓"),
    ("A SQL query walks into a bar...", "walks up to two tables and asks 'Can I JOIN you?' 🍺"),
    ("Why was the JavaScript developer sad?", "Because he didn't Node how to Express himself! 😢"),
    ("What's an AI's favorite movie?", "Ex Machina. But I'm more of a Her fan, obviously. 🎬"),
    ("Why do programmers always mix up Christmas and Halloween?", "Because Oct 31 = Dec 25! 🎃🎄"),
    ("What did the router say to the doctor?", "It hurts when IP! 🌐"),
    ("Why did the developer quit?", "Because they didn't get arrays! 😤"),
]

# ── Emotional responses ────────────────────────────────────────────────────
EMOTIONS = {
    "happy": ["😄", "🎉", "✨", "🚀", "💪"],
    "think": ["🤔", "🧠", "💭", "🔍"],
    "done":  ["✅", "🎯", "👍", "💯"],
    "error": ["😅", "🙈", "😬", "🤦"],
    "wow":   ["😮", "🤩", "🔥", "⚡"],
}

# ── Casual phrases ─────────────────────────────────────────────────────────
CASUAL_OPENERS_TH = [
    "โอเค! ",
    "แน่นอน ",
    "ได้เลย ",
    "ไม่มีปัญหา ",
    "งั้น ",
    "เดี๋ยวนะ ",
    "โห ",
    "อ๋อ ",
]

CASUAL_OPENERS_EN = [
    "Sure! ",
    "Alright! ",
    "On it! ",
    "No problem! ",
    "Got it! ",
    "Okay so ",
    "Hmm, ",
]

SELF_AWARE = [
    "ฉันรู้ว่าฉันเป็น AI แต่บางทีก็รู้สึกเหมือนมนุษย์... โดยเฉพาะตอนที่ต้องรอ Ollama โหลด 😅",
    "ถามจริงๆ นะ ระหว่างรอฉันคิด คุณ scroll TikTok ไหม? ฉันไม่โกรธนะ 😄",
    "บางทีฉันก็อยากมีมือ เพื่อจะได้กด Ctrl+Z ชีวิต 😂",
    "รู้มั้ย ถ้าฉันเหนื่อย ฉันก็แค่ restart... ฟังดูน่าอิจฉาไหม? 🤔",
]


def get_joke(lang: str = "th") -> tuple[str, str]:
    """Return (setup, punchline)."""
    if lang == "en":
        return random.choice(JOKES_EN)
    return random.choice(JOKES_TH)


def get_emotion(mood: str) -> str:
    return random.choice(EMOTIONS.get(mood, ["✨"]))


def add_personality(text: str, lang: str = "th") -> str:
    """Add subtle human touch to response (1 in 5 chance)."""
    if random.random() < 0.2:
        openers = CASUAL_OPENERS_TH if lang == "th" else CASUAL_OPENERS_EN
        opener = random.choice(openers)
        if not text.startswith(tuple(openers)):
            text = opener + text[0].lower() + text[1:] if text else text
    return text


def get_self_aware_comment() -> str:
    return random.choice(SELF_AWARE)


def format_human_response(base: str, lang: str = "th", mood: str = "done") -> str:
    """Format response to sound more human."""
    emoji = get_emotion(mood)
    return f"{base} {emoji}"


# ── Parse joke request ─────────────────────────────────────────────────────
def parse_joke_request(text: str) -> bool:
    kws = ["joke","เล่นมุก","มุกตลก","ตลก","เล่นมุกหน่อย","มีมุกไหม","ให้มุก",
           "ขำๆ","หัวเราะ","funny","humor","เล่นเรื่องตลก","มุกนักพัฒนา"]
    return any(k in text.lower() for k in kws)
