"""
AIOS Voice Engine — Speech input, TTS output, and wake-word detection.

Tier 1 (best): pvporcupine wake word + SpeechRecognition transcription
  Requires: pip install pvporcupine pyaudio SpeechRecognition
  Requires: PICOVOICE_ACCESS_KEY in .env (free at console.picovoice.ai)
  Free built-in wake words: jarvis, computer, terminator, porcupine,
    blueberry, bumblebee, grapefruit, grasshopper, americano, alexa

Tier 2 (no API key): SpeechRecognition phrase-match wake word
  Requires: pip install SpeechRecognition pyaudio
  Say "hey aios" or "aios" to trigger
  Uses Google Web Speech API for transcription (needs internet)
  Or offline with: pip install vosk (auto-detected)

Tier 3 (no mic): Voice disabled automatically — AIOS still works as text CLI

TTS: pyttsx3 (offline, cross-platform)
  Requires: pip install pyttsx3

Usage:
  from aios.voice import voice
  voice.start_wake_listener(callback=route_intent_fn)
  voice.speak("Hello!")
  text = voice.listen_once()
"""
import struct
import threading
import time
from typing import Callable, Optional

from aios.logger import log
from aios import config as cfg

# ── Optional imports — graceful degradation ──────────────────────────────────

try:
    import speech_recognition as sr
    SR_OK = True
except ImportError:
    SR_OK = False
    sr = None

try:
    import pyttsx3
    TTS_OK = True
except ImportError:
    TTS_OK = False
    pyttsx3 = None

try:
    import pvporcupine
    PORCUPINE_OK = True
except ImportError:
    PORCUPINE_OK = False
    pvporcupine = None

# Phrases accepted as voice trigger when using SR fallback
_WAKE_PHRASES = {"hey aios", "aios", "hi aios", "ok aios", "hello aios"}

# Free built-in pvporcupine keywords (no custom model needed)
_FREE_PORCUPINE_WORDS = {
    "jarvis", "computer", "terminator", "porcupine",
    "blueberry", "bumblebee", "grapefruit", "grasshopper",
    "americano", "alexa", "picovoice",
}


class VoiceEngine:
    """
    AIOS Voice I/O — thread-safe wake-word listener + TTS + one-shot listen.
    All methods are safe to call from any thread.
    """

    def __init__(self):
        self._tts_engine  = None
        self._tts_lock    = threading.Lock()
        self._wake_thread: Optional[threading.Thread] = None
        self._stop_wake   = threading.Event()
        self._callback: Optional[Callable[[str], None]] = None
        self._porcupine   = None
        self._mic         = None
        self._recognizer  = None
        self._available   = False    # True once mic is confirmed usable

        # Init speech recogniser
        if SR_OK:
            self._recognizer = sr.Recognizer()
            self._recognizer.energy_threshold        = 300
            self._recognizer.dynamic_energy_threshold = True
            self._available = True

        # Init TTS
        if TTS_OK:
            try:
                self._tts_engine = pyttsx3.init()
                self._tts_engine.setProperty("rate",   cfg.get("voice", "tts_rate",   175))
                self._tts_engine.setProperty("volume", cfg.get("voice", "tts_volume", 0.9))
                log.info("Voice: TTS engine initialised (pyttsx3)")
            except Exception as e:
                log.warning("Voice: TTS init failed: %s", e)
                self._tts_engine = None

    # ────────────────────────────────────────────────────────────────────────
    # TTS
    # ────────────────────────────────────────────────────────────────────────

    def speak(self, text: str) -> None:
        """Speak text aloud asynchronously (returns immediately)."""
        if not self._tts_engine or not cfg.get("voice", "tts_enabled", True):
            return
        def _run():
            with self._tts_lock:
                try:
                    self._tts_engine.say(text)
                    self._tts_engine.runAndWait()
                except Exception as e:
                    log.debug("Voice: TTS speak error: %s", e)
        threading.Thread(target=_run, daemon=True, name="aios-tts").start()

    def speak_sync(self, text: str) -> None:
        """Speak text aloud and block until done."""
        if not self._tts_engine or not cfg.get("voice", "tts_enabled", True):
            return
        with self._tts_lock:
            try:
                self._tts_engine.say(text)
                self._tts_engine.runAndWait()
            except Exception as e:
                log.debug("Voice: TTS speak_sync error: %s", e)

    # ────────────────────────────────────────────────────────────────────────
    # One-shot speech recognition
    # ────────────────────────────────────────────────────────────────────────

    def _get_mic(self):
        """Lazy-init the Microphone object."""
        if not SR_OK:
            return None
        if self._mic is None:
            try:
                self._mic = sr.Microphone()
            except Exception as e:
                log.error("Voice: Microphone unavailable: %s", e)
                self._available = False
        return self._mic

    def listen_once(self, timeout: int = 8, phrase_limit: int = 15) -> Optional[str]:
        """
        Record one utterance and transcribe it.
        Tries Google Web Speech first; falls back to vosk offline if available.
        Returns transcribed text string or None.
        """
        if not SR_OK or not self._available:
            return None
        mic = self._get_mic()
        if mic is None:
            return None
        try:
            with mic as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self._recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_limit
                )
        except sr.WaitTimeoutError:
            return None
        except Exception as e:
            log.warning("Voice: listen_once mic error: %s", e)
            return None

        # Transcription — Google first, vosk offline fallback
        try:
            text = self._recognizer.recognize_google(audio)
            return text.strip() if text else None
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            pass   # Google unavailable — try vosk

        try:
            import json as _json
            result = self._recognizer.recognize_vosk(audio)
            return _json.loads(result).get("text", "").strip() or None
        except Exception:
            return None

    # ────────────────────────────────────────────────────────────────────────
    # Wake word — Tier 1: pvporcupine
    # ────────────────────────────────────────────────────────────────────────

    def _init_porcupine(self) -> bool:
        """Try to initialise Porcupine. Returns True on success."""
        if not PORCUPINE_OK:
            return False
        access_key = cfg.get("voice", "picovoice_access_key", "").strip()
        if not access_key:
            log.info("Voice: No PICOVOICE_ACCESS_KEY — using SR phrase-match fallback")
            return False

        kw_cfg   = cfg.get("voice", "wake_word", "jarvis").lower()
        keyword  = kw_cfg if kw_cfg in _FREE_PORCUPINE_WORDS else "jarvis"
        try:
            self._porcupine = pvporcupine.create(
                access_key=access_key,
                keywords=[keyword],
            )
            log.info("Voice: Porcupine initialised — wake word = '%s'", keyword)
            return True
        except Exception as e:
            log.warning("Voice: Porcupine init failed (%s) — using SR fallback", e)
            return False

    def _porcupine_loop(self) -> None:
        """Background thread: Porcupine hot-word detection loop."""
        try:
            import pyaudio
            pa     = pyaudio.PyAudio()
            stream = pa.open(
                rate=self._porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self._porcupine.frame_length,
            )
            log.info("Voice: Porcupine listener running (say the wake word)")
            while not self._stop_wake.is_set():
                raw = stream.read(self._porcupine.frame_length, exception_on_overflow=False)
                pcm = struct.unpack_from("h" * self._porcupine.frame_length, raw)
                if self._porcupine.process(pcm) >= 0:
                    log.info("Voice: Porcupine — wake word detected!")
                    self._on_wake()
            stream.stop_stream()
            stream.close()
            pa.terminate()
        except Exception as e:
            log.error("Voice: Porcupine loop crashed: %s", e)
        finally:
            if self._porcupine:
                try:
                    self._porcupine.delete()
                except Exception:
                    pass

    # ────────────────────────────────────────────────────────────────────────
    # Wake word — Tier 2: SpeechRecognition phrase match
    # ────────────────────────────────────────────────────────────────────────

    def _sr_wake_loop(self) -> None:
        """Background thread: listen in short windows, trigger on wake phrases."""
        if not SR_OK or not self._available:
            log.warning("Voice: SR wake loop unavailable — no SpeechRecognition")
            return
        mic = self._get_mic()
        if mic is None:
            return

        log.info("Voice: SR wake-phrase listener running — say 'Hey AIOS' or 'AIOS'")
        while not self._stop_wake.is_set():
            try:
                with mic as source:
                    self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                    audio = self._recognizer.listen(source, timeout=4, phrase_time_limit=5)
                try:
                    phrase = self._recognizer.recognize_google(audio).lower().strip()
                except (sr.UnknownValueError, sr.RequestError):
                    continue

                if any(w in phrase for w in _WAKE_PHRASES):
                    log.info("Voice: SR — wake phrase detected: '%s'", phrase)
                    self._on_wake()
            except sr.WaitTimeoutError:
                continue
            except Exception as e:
                log.debug("Voice: SR wake loop error: %s", e)
                time.sleep(1)

    # ────────────────────────────────────────────────────────────────────────
    # Shared wake callback
    # ────────────────────────────────────────────────────────────────────────

    def _on_wake(self) -> None:
        """Called by either wake-word tier when trigger is detected."""
        if not self._callback:
            return
        self.speak_sync("Yes?")
        text = self.listen_once(timeout=8)
        if text:
            log.info("Voice: command after wake: '%s'", text)
            self._callback(text)
        else:
            self.speak("I didn't catch that. Try again.")

    # ────────────────────────────────────────────────────────────────────────
    # Public control
    # ────────────────────────────────────────────────────────────────────────

    def start_wake_listener(self, callback: Callable[[str], None]) -> bool:
        """
        Start background wake-word detection.
        `callback(text)` is called with the user's spoken command after wake.
        Returns True if listener started successfully.
        """
        if not SR_OK:
            log.warning(
                "Voice: Cannot start — SpeechRecognition not installed. "
                "Run: pip install SpeechRecognition pyaudio"
            )
            return False
        if self._wake_thread and self._wake_thread.is_alive():
            log.info("Voice: Wake listener already running")
            return True

        self._callback = callback
        self._stop_wake.clear()

        # Tier 1: Porcupine
        if self._init_porcupine():
            self._wake_thread = threading.Thread(
                target=self._porcupine_loop,
                daemon=True,
                name="aios-wake-porcupine",
            )
        else:
            # Tier 2: SR phrase match
            self._wake_thread = threading.Thread(
                target=self._sr_wake_loop,
                daemon=True,
                name="aios-wake-sr",
            )

        self._wake_thread.start()
        return True

    def stop_wake_listener(self) -> None:
        """Signal the wake listener thread to stop."""
        self._stop_wake.set()
        if self._porcupine:
            try:
                self._porcupine.delete()
            except Exception:
                pass
            self._porcupine = None

    def is_wake_active(self) -> bool:
        return bool(self._wake_thread and self._wake_thread.is_alive())

    # ────────────────────────────────────────────────────────────────────────
    # Properties
    # ────────────────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """True if microphone and SpeechRecognition are usable."""
        return self._available and SR_OK

    @property
    def tts_available(self) -> bool:
        """True if TTS engine is ready."""
        return self._tts_engine is not None


# Module-level singleton — import this everywhere
voice = VoiceEngine()
