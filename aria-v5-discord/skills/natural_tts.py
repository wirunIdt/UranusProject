"""
Natural TTS — Female Thai Voice
Primary  : edge-tts  th-TH-PremwadeeNeural (Microsoft Neural, female, natural)
Fallback : pyttsx3 offline

Make speech sound human:
- Natural pace with pauses
- Remove markdown / emojis before speaking
- Split long text into sentences
"""
import asyncio, threading, queue, os, re, platform, subprocess, shutil, tempfile

SYSTEM = platform.system()

# ── Voice config ────────────────────────────────────────────────────────────
VOICES = {
    "th": "th-TH-PremwadeeNeural",   # Female, natural Thai
    "en": "en-US-JennyNeural",        # Female, natural English
}
RATE  = "-5%"   # Slightly slower = more natural
PITCH = "+0Hz"


def _clean_text(text: str) -> str:
    """Remove markdown, emojis, code blocks — keep only speakable text."""
    # Remove code blocks
    text = re.sub(r'```[\s\S]*?```', 'มีโค้ดตัวอย่าง', text)
    text = re.sub(r'`[^`]+`', '', text)
    # Remove markdown bold/italic
    text = re.sub(r'\*+([^*]+)\*+', r'\1', text)
    text = re.sub(r'_+([^_]+)_+', r'\1', text)
    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    # Remove emojis
    text = re.sub(r'[\U00010000-\U0010ffff]', '', text, flags=re.UNICODE)
    text = re.sub(r'[^\w\s\u0E00-\u0E7F.,!?:;()\-]', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:800]


class NaturalTTS:
    def __init__(self, lang: str = "th"):
        self.lang            = lang
        self._queue          = queue.Queue()
        self._edge_available = False
        self._pyttsx_engine  = None
        self._pyttsx_avail   = False

        self._check_edge()
        self._init_pyttsx()
        threading.Thread(target=self._worker, daemon=True).start()

    def _check_edge(self):
        try:
            import edge_tts
            self._edge_available = True
        except ImportError:
            pass

    def _init_pyttsx(self):
        try:
            import pyttsx3
            e = pyttsx3.init()
            e.setProperty("rate", 155)
            e.setProperty("volume", 1.0)
            # Try to find female voice
            voices = e.getProperty("voices")
            for v in voices:
                name = (v.name or "").lower()
                if any(x in name for x in ["zira","hazel","female","woman","girl","premwadee"]):
                    e.setProperty("voice", v.id)
                    break
            self._pyttsx_engine = e
            self._pyttsx_avail  = True
        except Exception as e:
            print(f"[TTS] pyttsx3 unavailable: {e}")

    # ── Worker ───────────────────────────────────────────────────────────────

    def _worker(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            text, lang = item
            try:
                if self._edge_available:
                    asyncio.run(self._speak_edge(text, lang))
                elif self._pyttsx_avail:
                    self._speak_pyttsx(text)
            except Exception as e:
                print(f"[TTS] speak error: {e}")
                # Fallback
                if self._pyttsx_avail:
                    try: self._speak_pyttsx(text)
                    except: pass
            finally:
                self._queue.task_done()

    # ── edge-tts (neural) ────────────────────────────────────────────────────

    async def _speak_edge(self, text: str, lang: str):
        import edge_tts
        voice = VOICES.get(lang, VOICES["th"])
        comm  = edge_tts.Communicate(text, voice, rate=RATE, pitch=PITCH)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp = f.name
        try:
            await comm.save(tmp)
            self._play(tmp)
        finally:
            try: os.unlink(tmp)
            except: pass

    def _play(self, path: str):
        """Play audio file — cross-platform."""
        if SYSTEM == "Windows":
            # Try playsound
            try:
                from playsound import playsound
                playsound(path, block=True); return
            except ImportError:
                pass
            # pygame fallback
            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
                import time
                while pygame.mixer.music.get_busy(): time.sleep(0.05)
                pygame.mixer.music.stop(); return
            except ImportError:
                pass
            # Windows Media Player via subprocess
            try:
                subprocess.run(
                    ["powershell", "-c", f"(New-Object Media.SoundPlayer '{path}').PlaySync()"],
                    capture_output=True, timeout=30)
            except Exception as e:
                print(f"[TTS] play error: {e}")
        elif SYSTEM == "Darwin":
            subprocess.run(["afplay", path], capture_output=True)
        else:
            for player in ["mpg123", "ffplay", "mpv", "mplayer"]:
                if shutil.which(player):
                    args = ["ffplay", "-nodisp", "-autoexit", path] if player == "ffplay" \
                           else [player, "-q", path]
                    subprocess.run(args, capture_output=True)
                    return

    # ── pyttsx3 fallback ─────────────────────────────────────────────────────

    def _speak_pyttsx(self, text: str):
        e = self._pyttsx_engine
        if not e: return
        try:
            e.say(text)
            e.runAndWait()
        except RuntimeError:
            try:
                import pyttsx3
                e = pyttsx3.init()
                e.setProperty("rate", 155)
                self._pyttsx_engine = e
                e.say(text)
                e.runAndWait()
            except Exception as ex:
                print(f"[TTS] pyttsx3 restart error: {ex}")

    # ── Public API ────────────────────────────────────────────────────────────

    def speak(self, text: str, lang: str | None = None):
        """Queue text for TTS. Non-blocking."""
        use_lang = lang or self.lang
        clean    = _clean_text(text)
        if clean:
            self._queue.put((clean, use_lang))

    def speak_immediate(self, text: str, lang: str | None = None):
        """Clear queue and speak immediately."""
        while not self._queue.empty():
            try: self._queue.get_nowait()
            except: break
        self.speak(text, lang)

    def is_available(self) -> bool:
        return self._edge_available or self._pyttsx_avail

    def mode(self) -> str:
        if self._edge_available:  return "🎙️ Neural (edge-tts female)"
        if self._pyttsx_avail:   return "🤖 Basic (pyttsx3)"
        return "❌ N/A"

    def stop(self):
        if self._pyttsx_avail and self._pyttsx_engine:
            try: self._pyttsx_engine.stop()
            except: pass

    def cleanup(self):
        self._queue.put(None)
        self.stop()
