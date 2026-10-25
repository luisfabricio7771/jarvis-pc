"""Public wake-word interface; activation is local and Spanish-capable."""
from core.keyword_wake import (
    WakeWordDetector, SpeechWindow, WAKE_PHRASE, WAKE_MODEL, SAMPLE_RATE,
    DEFAULT_THRESHOLD, MODEL_DIR, matches_keyword, is_installed, is_ready,
    install_and_download,
)
