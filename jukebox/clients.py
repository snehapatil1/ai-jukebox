"""HTTP clients for the four class services (formats verified by live probes):

- 9001 Qwen3.6-35B     POST /v1/chat/completions        (OpenAI-compatible)
- 9006 FLUX.2 klein 4B POST /v1/images/generations      -> data[0].b64_json PNG
- 9007 ACE-Step        POST /release_task -> poll /query_result -> GET /v1/audio
- 9008 Chatterbox V3   POST /v1/audio/speech            -> audio bytes (MP3)

Credentials are only sent in the Authorization header and are never logged.
"""
from __future__ import annotations

import base64
import json
import logging
import time
import urllib.parse
import uuid

import requests

from . import config

log = logging.getLogger("jukebox.clients")


class ServiceError(RuntimeError):
    """Raised when a class service fails or returns an unexpected format."""


# ---------------------------------------------------------------------------
# low-level helpers
# ---------------------------------------------------------------------------
class _Requester:
    """Tiny wrapper that logs requests WITHOUT headers or keys."""

    def __init__(self, base_url: str) -> None:
        self.base = base_url
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"

    def request(self, method: str, path: str, *, json_body=None, timeout=120) -> requests.Response:
        url = self.base.rstrip("/") + path
        started = time.monotonic()
        try:
            resp = self.session.request(method, url, json=json_body, timeout=timeout)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            log.info("%s %s -> %s (%d ms)", method, path, resp.status_code, elapsed_ms)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            log.warning("%s %s -> FAILED after %d ms: %s", method, path, elapsed_ms, exc)
            body = getattr(exc.response, "text", "") or ""
            raise ServiceError(f"{method} {path} failed: {exc} {body[:300]}") from exc

    def get(self, path: str, timeout=120) -> requests.Response:
        return self.request("GET", path, timeout=timeout)

    def post(self, path: str, json_body=None, timeout=120) -> requests.Response:
        return self.request("POST", path, json_body=json_body, timeout=timeout)


# ---------------------------------------------------------------------------
# 9001 — Qwen text generation (reasoning model; needs roomy max_tokens)
# ---------------------------------------------------------------------------
_llm = _Requester(config.BASE_URL_LLM)


def qwen_chat(system: str, user: str, max_tokens: int = 2048, temperature: float = 0.0) -> str:
    """One chat-completion call. Returns the assistant content (may be "").

    ``enable_thinking: False`` is deliberate: this is a reasoning model whose
    internal chain can consume thousands of tokens (verified up to 8k+) and
    then return empty content when it hits the budget. With thinking disabled
    the same model answers reliably in well under a second for these creative
    tasks. Temperature is still pinned at 0; the class server does not expose
    a working seed, so outputs are not byte-identical across runs.
    """
    if max_tokens < 1024:
        raise ServiceError(f"max_tokens={max_tokens} is too small; use >= 1024")
    resp = _llm.post(
        "/chat/completions",
        json_body={
            "model": config.MODEL_LLM,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=300,
    )
    try:
        payload = resp.json()
        content = payload["choices"][0]["message"].get("content") or ""
    except (ValueError, KeyError, IndexError) as exc:
        raise ServiceError(f"Unexpected chat response shape: {exc}") from exc
    return content.strip()


def qwen_chat_with_fallback(
    system: str,
    user: str,
    *,
    max_tokens: int = 2048,
    fallback_truncations: tuple[int, ...] = (120, 40),
) -> str:
    """Retry ladder for the reasoning model's occasional empty replies.

    The model sometimes returns empty content for a given (system, user) pair;
    retrying the same text usually succeeds, and shortening the user text side-
    steps reproducible empties. Order: full text x2 -> truncated chains.
    """
    candidates = [user]
    for length in fallback_truncations:
        if len(user) > length:
            candidates.append(f"[shortened prompt]\n{user[:length]}")
    for idx, candidate in enumerate(candidates):
        content = qwen_chat(system, candidate, max_tokens=max_tokens)
        if content:
            return content
        log.warning("qwen empty content on attempt %d/%d", idx + 1, len(candidates))
    return ""


# ---------------------------------------------------------------------------
# 9006 — FLUX cover art
# ---------------------------------------------------------------------------
_img = _Requester(config.BASE_URL_IMAGE)


def generate_image(prompt: str, size: str = "1024x1024") -> bytes:
    """Render an image from a text prompt. Returns PNG bytes."""
    resp = _img.post(
        "/images/generations",
        json_body={"model": config.MODEL_IMAGE, "prompt": prompt, "n": 1, "size": size},
        timeout=300,
    )
    try:
        data = resp.json()["data"][0]
    except (ValueError, KeyError, IndexError) as exc:
        raise ServiceError(f"Unexpected image response shape: {exc}") from exc
    if data.get("b64_json"):
        return base64.b64decode(data["b64_json"])
    if data.get("url"):
        return _img.get(data["url"], timeout=120).content
    raise ServiceError("Image response contained neither b64_json nor url")


# ---------------------------------------------------------------------------
# 9007 — ACE-Step music generation (async task API)
# ---------------------------------------------------------------------------
_music = _Requester(config.BASE_URL_MUSIC)


def generate_music(
    prompt: str,
    lyrics: str = "",
    duration_sec: float = 30.0,
    poll_interval: float = 8.0,
    max_wait: float = 600.0,
) -> tuple[bytes, dict]:
    """Submit a text2music task and download the finished audio (MP3).

    Format verified against the ACE-Step 1.5 API docs and live probes:
    release_task -> query_result (status 1 = done, 2 = failed) -> /v1/audio?path=...
    The service returns two generated variants; the first successful one is kept.
    """
    duration_sec = max(config.DURATION_MIN, min(float(duration_sec), 600.0))
    body: dict = {
        "prompt": prompt,
        "lyrics": lyrics if lyrics else "",
        "audio_duration": duration_sec,
        "audio_format": "mp3",
        "vocal_language": "en",
    }
    if config.MODEL_MUSIC:
        body["model"] = config.MODEL_MUSIC

    resp = _music.post("/release_task", json_body=body, timeout=120)
    try:
        data = resp.json().get("data") or {}
        task_id = data.get("task_id")
    except ValueError as exc:
        raise ServiceError(f"release_task returned non-JSON: {exc}") from exc
    if not task_id:
        raise ServiceError(f"release_task did not return a task_id: {resp.text[:200]}")

    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        q = _music.post(
            "/query_result", json_body={"task_id_list": [task_id]}, timeout=120
        )
        try:
            items = q.json().get("data") or []
        except ValueError as exc:
            raise ServiceError(f"query_result returned non-JSON: {exc}") from exc
        if not items:
            continue
        item = items[0]
        status = item.get("status")
        if status == 0:  # still running
            continue
        result_raw = item.get("result") or ""
        try:
            variants = json.loads(result_raw) if result_raw else []
        except json.JSONDecodeError:
            variants = []
        if status == 2 or not any(v.get("status") == 1 and v.get("file") for v in variants):
            raise ServiceError(
                f"Music generation failed (task {task_id}): {result_raw[:300]}"
            )
        first = next(v for v in variants if v.get("status") == 1 and v.get("file"))
        meta = first.get("metas") or {}
        audio = _music.get(first["file"], timeout=180).content
        if not audio:
            raise ServiceError("Music task finished but downloaded 0 bytes")
        return audio, {**meta, "task_id": task_id}

    raise ServiceError(f"Music generation timed out after {max_wait:.0f}s (task {task_id})")


# ---------------------------------------------------------------------------
# 9008 — Chatterbox TTS
# ---------------------------------------------------------------------------
_tts = _Requester(config.BASE_URL_TTS)


def speak(
    text: str,
    *,
    ref_audio_b64: str | None = None,
    voice_id: str | None = None,
    language_id: str = "en",
    response_format: str = "mp3",
) -> bytes:
    """Synthesize speech. Default bundled voice unless a voice/ref is given."""
    text = text.strip()
    if not text:
        raise ServiceError("speak() called with empty text")
    if len(text) > config.TTS_MAX_TEXT_CHARS:
        text = text[: config.TTS_MAX_TEXT_CHARS]
    body: dict = {
        "model": config.MODEL_TTS,
        "input": text,
        "language_id": language_id,
        "response_format": response_format,
        "speed": 1.0,
    }
    if voice_id:
        body["voice"] = voice_id
    if ref_audio_b64:
        body["ref_audio"] = ref_audio_b64
    resp = _tts.post("/v1/audio/speech", json_body=body, timeout=300)
    audio = resp.content
    if not audio:
        raise ServiceError("TTS returned empty audio")
    return audio


def encode_ref_audio(file_bytes: bytes) -> str:
    return base64.b64encode(file_bytes).decode("ascii")


# ---------------------------------------------------------------------------
# placeholder cover (generated locally, nothing bundled)
# ---------------------------------------------------------------------------
def make_placeholder_cover(text: str = "No cover yet", size: int = 512) -> bytes:
    """Draw a simple placeholder PNG with PIL (no bundled artwork)."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (size, size), (24, 24, 34))
    draw = ImageDraw.Draw(img)
    for i in range(size):
        shade = int(24 + 30 * (i / size))
        draw.line([(0, i), (size, i)], fill=(shade, shade, shade + 12))
    try:
        font_big = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 120)
        font_small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
    except OSError:
        font_big = font_small = ImageFont.load_default()
    draw.text((size / 2, size / 2 - 40), "\u266b", font=font_big, fill=(200, 200, 220), anchor="mm")
    draw.text((size / 2, size / 2 + 90), text, font=font_small, fill=(180, 180, 200), anchor="mm")
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def new_filename(ext: str) -> str:
    return f"{uuid.uuid4().hex[:12]}{ext}"
