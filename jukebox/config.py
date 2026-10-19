"""Configuration for the AI Jukebox.

All credentials come from environment variables or a gitignored `.env` file
(see `.env.example` for placeholders). Base URLs default to the class
endpoints defined in class-endpoints.txt and can be overridden per-service.

Fail-fast: the app refuses to start without an API key (never a default in code).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths (all relative to the repository root; no hardcoded machine paths)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
AUDIO_DIR = DATA_DIR / "audio"          # generated songs
COVER_DIR = DATA_DIR / "covers"         # generated cover art
DJ_DIR = DATA_DIR / "dj"                # generated DJ clips (cached)
VOICE_DIR = DATA_DIR / "voice_refs"     # user voice references (gitignored temp)
LIBRARY_FILE = DATA_DIR / "library.json"

for _d in (AUDIO_DIR, COVER_DIR, DJ_DIR, VOICE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _load_dotenv() -> None:
    load_dotenv(ROOT / ".env")
    load_dotenv()  # also honor process environment


def _env(name: str, default: str = "") -> str:
    value = __import__("os").environ.get(name)
    return value if value not in (None, "") else default


_load_dotenv()

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
LLM_API_KEY = _env("LLM_API_KEY")

# ---------------------------------------------------------------------------
# Service endpoints (class services only; port 9000 is reserved for Hermes)
# ---------------------------------------------------------------------------
BASE_URL_LLM = _env("BASE_URL_LLM", "http://dobolyi.com:9001/v1")          # Qwen3.6-35B text
BASE_URL_IMAGE = _env("BASE_URL_IMAGE", "http://dobolyi.com:9006/v1")      # FLUX.2 klein 4B
BASE_URL_MUSIC = _env("BASE_URL_MUSIC", "http://dobolyi.com:9007")         # ACE-Step 1.5 XL Turbo
BASE_URL_TTS = _env("BASE_URL_TTS", "http://dobolyi.com:9008")             # Chatterbox V3

MODEL_LLM = _env("MODEL_LLM", "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit")
MODEL_IMAGE = _env("MODEL_IMAGE", "black-forest-labs/FLUX.2-klein-4B")
MODEL_TTS = _env("MODEL_TTS", "chatterbox-v3")

# ACE-Step: omit `model` to use the server's default (verified working);
# the full id can be forced via env if the server setup changes.
MODEL_MUSIC = _env("MODEL_MUSIC", "")  # e.g. "acestep/acestep-v15-xl-turbo"

# ---------------------------------------------------------------------------
# App behavior
# ---------------------------------------------------------------------------
DURATION_MIN = 10
DURATION_MAX = 120          # enforced in code; 10-600 is the service limit
DURATION_DEFAULT = 30
VOICE_MAX_BYTES = 15 * 1024 * 1024     # TTS reference cap is 20 MB / 60 s
TTS_MAX_TEXT_CHARS = 4000              # server limit is 4096

# How long to wait for a prefetched DJ clip before generating synchronously
# (seconds). Keeps the queue moving when commentary is slow.
DJ_WAIT_FOR_PREFETCH = 150

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


def check_config() -> None:
    """Fail fast at startup if required configuration is missing."""
    if not LLM_API_KEY:
        sys.exit(
            "[AI Jukebox] Missing LLM_API_KEY. Copy .env.example to .env and set "
            "the key provided in class-endpoints.txt, then re-run `python app.py`."
        )
