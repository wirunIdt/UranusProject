"""modules/alerts.py — Free alert channels: ntfy, Telegram, LINE Notify, WhatsApp (CallMeBot)"""
import os, requests

NTFY_SERVER    = os.environ.get("NTFY_SERVER",     "https://ntfy.sh")
NTFY_TOPIC     = os.environ.get("NTFY_TOPIC",      "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN",  "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT",   "")
LINE_TOKEN     = os.environ.get("LINE_TOKEN",       "")
CALLMEBOT_PHONE= os.environ.get("CALLMEBOT_PHONE", "")
CALLMEBOT_KEY  = os.environ.get("CALLMEBOT_KEY",   "")

def _topic(node_id: str) -> str:
    return NTFY_TOPIC or f"aria-alerts-{node_id[:8]}"

def send_ntfy(title: str, message: str, priority: str = "default", node_id: str = "00000000") -> dict:
    try:
        r = requests.post(
            f"{NTFY_SERVER}/{_topic(node_id)}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority, "Tags": "robot,bell"},
            timeout=8,
        )
        return {"ok": r.status_code < 300, "status": r.status_code,
                "topic": _topic(node_id), "server": NTFY_SERVER}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send_telegram(title: str, message: str) -> dict:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return {"ok": False, "error": "Set TELEGRAM_TOKEN + TELEGRAM_CHAT env vars"}
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT,
                  "text": f"*{title}*\n{message}",
                  "parse_mode": "Markdown"},
            timeout=8,
        )
        return {"ok": r.status_code == 200}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send_line(title: str, message: str) -> dict:
    if not LINE_TOKEN:
        return {"ok": False, "error": "Set LINE_TOKEN env var (notify-bot.line.me)"}
    try:
        r = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {LINE_TOKEN}"},
            data={"message": f"\n{title}\n{message}"},
            timeout=8,
        )
        return {"ok": r.status_code == 200}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send_whatsapp(title: str, message: str) -> dict:
    if not CALLMEBOT_PHONE or not CALLMEBOT_KEY:
        return {"ok": False, "error": "Set CALLMEBOT_PHONE + CALLMEBOT_KEY env vars"}
    try:
        text = requests.utils.quote(f"{title}: {message}")
        r = requests.get(
            f"https://api.callmebot.com/whatsapp.php"
            f"?phone={CALLMEBOT_PHONE}&text={text}&apikey={CALLMEBOT_KEY}",
            timeout=10,
        )
        return {"ok": "Message queued" in r.text or r.status_code == 200}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send(title: str, message: str, channel: str = "ntfy",
         priority: str = "default", node_id: str = "00000000") -> dict:
    results = {}
    if channel in ("ntfy","all"):
        results["ntfy"] = send_ntfy(title, message, priority, node_id)
    if channel in ("telegram","all"):
        results["telegram"] = send_telegram(title, message)
    if channel in ("line","all"):
        results["line"] = send_line(title, message)
    if channel in ("whatsapp","all"):
        results["whatsapp"] = send_whatsapp(title, message)
    return {
        "ok": any(v.get("ok") for v in results.values()),
        "results": results,
        "topic": _topic(node_id),
    }

def config(node_id: str = "00000000") -> dict:
    return {
        "ntfy":     {"available": True,                             "topic": _topic(node_id), "server": NTFY_SERVER,
                     "note": "Free, no signup. Install ntfy app → subscribe to topic."},
        "telegram": {"available": bool(TELEGRAM_TOKEN and TELEGRAM_CHAT),
                     "note": "Set TELEGRAM_TOKEN + TELEGRAM_CHAT. Get token from @BotFather."},
        "line":     {"available": bool(LINE_TOKEN),
                     "note": "Set LINE_TOKEN. Get from notify-bot.line.me (free)."},
        "whatsapp": {"available": bool(CALLMEBOT_PHONE and CALLMEBOT_KEY),
                     "note": "Set CALLMEBOT_PHONE + CALLMEBOT_KEY. See callmebot.com."},
    }
