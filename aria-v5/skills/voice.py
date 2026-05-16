"""
Voice Skills v2 — Offline-first
- TTS  : pyttsx3 (offline, ไม่ต้องใช้เน็ต) พร้อม fallback restart
- STT  : faster-whisper (offline) → Google (online fallback)
"""
import threading, queue, platform

SYSTEM = platform.system()


class VoiceManager:
    def __init__(self):
        self.is_listening       = False
        self._tts_engine        = None
        self._tts_available     = False
        self._sr_available      = False
        self._whisper_available = False
        self._tts_queue: queue.Queue = queue.Queue()
        self._init_tts()
        self._check_stt()

    def _init_tts(self):
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 150)
            engine.setProperty("volume", 1.0)
            voices = engine.getProperty("voices")
            for v in voices:
                for l in (v.languages or []):
                    if isinstance(l, bytes): l = l.decode("utf-8","ignore")
                    if "th" in l.lower():
                        engine.setProperty("voice", v.id)
                        break
            self._tts_engine    = engine
            self._tts_available = True
            threading.Thread(target=self._tts_worker, daemon=True).start()
        except ImportError:
            pass
        except Exception as e:
            print(f"[TTS] init: {e}")

    def _check_stt(self):
        try:
            import faster_whisper
            self._whisper_available = True
        except ImportError:
            pass
        try:
            import speech_recognition
            self._sr_available = True
        except ImportError:
            pass

    def _tts_worker(self):
        while True:
            text = self._tts_queue.get()
            if text is None: break
            try:
                engine = self._tts_engine
                if engine:
                    try:
                        engine.say(text)
                        engine.runAndWait()
                    except RuntimeError:
                        import pyttsx3
                        engine = pyttsx3.init()
                        engine.setProperty("rate", 150)
                        engine.setProperty("volume", 1.0)
                        self._tts_engine = engine
                        engine.say(text)
                        engine.runAndWait()
            except Exception as e:
                print(f"[TTS] speak: {e}")
            finally:
                self._tts_queue.task_done()

    def speak(self, text: str):
        if not self._tts_available: return
        clean = "".join(ch for ch in text[:600] if ord(ch) < 0x10000).strip()
        if clean: self._tts_queue.put(clean)

    def stop_speaking(self):
        try:
            if self._tts_engine: self._tts_engine.stop()
        except Exception: pass

    def listen_once(self, on_result, on_error=None, language="th", timeout=8):
        if not (self._whisper_available or self._sr_available):
            if on_error:
                on_error("ไม่มี STT\nติดตั้ง offline: pip install faster-whisper sounddevice\nหรือ online: pip install SpeechRecognition PyAudio")
            return

        def _run():
            self.is_listening = True
            try:
                if self._whisper_available:
                    self._whisper(on_result, on_error, language, timeout)
                else:
                    self._google(on_result, on_error, language, timeout)
            finally:
                self.is_listening = False

        threading.Thread(target=_run, daemon=True).start()

    def _whisper(self, on_result, on_error, language, timeout):
        try:
            import sounddevice as sd, numpy as np
            from faster_whisper import WhisperModel
            sr = 16000
            audio = sd.rec(int(min(timeout,12)*sr), samplerate=sr, channels=1, dtype="float32")
            sd.wait()
            model = WhisperModel("small", device="cpu", compute_type="int8")
            lang  = "th" if language.startswith("th") else "en"
            segs, _ = model.transcribe(audio.flatten(), language=lang, beam_size=3, vad_filter=True)
            text = " ".join(s.text for s in segs).strip()
            if text: on_result(text)
            elif on_error: on_error("ไม่ได้ยินเสียง ลองพูดใหม่")
        except ImportError:
            if self._sr_available: self._google(on_result, on_error, language, timeout)
            elif on_error: on_error("ติดตั้ง: pip install sounddevice faster-whisper")
        except Exception as e:
            if on_error: on_error(f"[Whisper] {e}")

    def _google(self, on_result, on_error, language, timeout):
        try:
            import speech_recognition as sr_lib
            r = sr_lib.Recognizer()
            lang_code = "th-TH" if language.startswith("th") else "en-US"
            with sr_lib.Microphone() as src:
                r.adjust_for_ambient_noise(src, duration=0.4)
                audio = r.listen(src, timeout=timeout, phrase_time_limit=15)
            text = r.recognize_google(audio, language=lang_code)
            on_result(text)
        except sr_lib.WaitTimeoutError:
            if on_error: on_error("หมดเวลา ไม่ได้ยินเสียง")
        except sr_lib.UnknownValueError:
            if on_error: on_error("ไม่เข้าใจเสียง ลองพูดอีกครั้ง")
        except sr_lib.RequestError:
            if on_error: on_error("❌ Google STT ต้องการอินเทอร์เน็ต\nลอง: pip install faster-whisper sounddevice")
        except Exception as e:
            if on_error: on_error(str(e))

    def is_tts_available(self) -> bool: return self._tts_available
    def is_stt_available(self) -> bool: return self._whisper_available or self._sr_available
    def stt_mode(self) -> str:
        if self._whisper_available: return "🟢 Offline (Whisper)"
        if self._sr_available:      return "🌐 Online (Google)"
        return "❌ N/A"

    def cleanup(self):
        self._tts_queue.put(None)
        self.stop_speaking()
