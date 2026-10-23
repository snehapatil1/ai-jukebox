"""High-level orchestration for the AI Jukebox.

Each pipeline step calls a verified class service (see clients.py) and never
calls out to any paid or third-party service.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

from . import clients, config, prompts
from .library import Song

log = logging.getLogger("jukebox.service")


class PipelineError(RuntimeError):
    """A user-visible pipeline failure (message is safe to show in the UI)."""


# ---------------------------------------------------------------------------
# 1. Song title + lyrics (Qwen, port 9001)
# ---------------------------------------------------------------------------
def _clean_title(raw: str) -> str:
    raw = (raw or "").strip().strip('"\u201c\u201d')
    if raw.lower().startswith("title:"):
        raw = raw.split(":", 1)[1].strip()
    return raw[:60]


def write_song_draft(
    style: str, mood: str, duration_sec: float, instrumental: bool, theme: str
) -> dict:
    """Return {"title": str, "lyrics": str}. Lyrics is "" for instrumentals."""
    theme = (theme or "").strip()
    duration_sec = max(config.DURATION_MIN, min(float(duration_sec), config.DURATION_MAX))

    kind = "instrumental" if instrumental else "vocal"
    title = clients.qwen_chat_with_fallback(
        prompts.TITLE_SYSTEM,
        prompts.TITLE_USER.format(style=style, mood=mood, theme=theme or "none", kind=kind),
        max_tokens=2048,
        fallback_truncations=(60,),
    )
    title = _clean_title(title)
    if not title:
        raise PipelineError("Could not write a song title — please try again.")
    if instrumental:
        return {"title": title, "lyrics": ""}

    words = max(24, int(duration_sec * 2.2))  # ~2.2 sung words per second
    lyrics = clients.qwen_chat_with_fallback(
        prompts.LYRICS_SYSTEM.format(dur=int(duration_sec), words=words),
        prompts.LYRICS_USER.format(style=style, mood=mood, theme=theme or "none",
                                   dur=int(duration_sec)),
        max_tokens=2048,
    )
    if not lyrics:
        raise PipelineError("Could not write lyrics — please try again.")
    if len(lyrics) < 8:
        raise PipelineError("The lyrics came back too short to sing — please try again.")
    return {"title": title, "lyrics": lyrics}


# ---------------------------------------------------------------------------
# 2. Music generation (ACE-Step, port 9007)
# ---------------------------------------------------------------------------
def compose_music(
    style: str, mood: str, theme: str, duration_sec: float, lyrics: str
) -> tuple[Path, dict]:
    """Generate the audio file. Returns (absolute path, service metadata)."""
    theme = (theme or "").strip()
    # Build a detailed prompt for ACE-Step with instrumentation and production cues.
    style_desc = {
        "rock": "electric guitars, driving drums, bass line",
        "pop": "clean production, catchy melody, polished synths",
        "hip hop": "808 bass, crisp snares, rhythmic beats",
        "jazz": "saxophone or piano, upright bass, brushed drums",
        "ambient": "atmospheric pads, reverb-drenched textures, slow evolving harmonies",
        "metal": "distorted guitars, double-kick drums, aggressive tone",
        "electronic": "synthesizers, drum machines, electronic textures",
        "folk": "acoustic guitar, fiddle, warm organic feel",
        "classical": "string quartet or orchestra, dynamic swells",
        "r&b": "smooth bass groove, soulful keys, tight rhythm section",
        "country": "twangy guitars, pedal steel, storytelling feel",
    }.get(style.lower(), f"{style} instrumentation")
    
    mood_desc = {
        "happy": "uplifting major key, bright energy",
        "sad": "minor key, emotional depth, melancholic tones",
        "dark": "dminishing harmonies, tense atmosphere, brooding mood",
        "energetic": "fast tempo, driving rhythm, intense dynamics",
        "calm": "slow tempo, gentle dynamics, peaceful mood",
        "dreamy": "ethereal textures, floating harmonies, reverberant space",
        "aggressive": "hard-hitting rhythms, sharp attacks, intense delivery",
        "romantic": "warm harmonies, intimate feel, lyrical melodies",
        "nostalgic": "vintage warmth, bittersweet tonality, retro character",
        "epic": "grand crescendos, wide dynamic range, cinematic sweep",
    }.get(mood.lower(), f"{mood} atmosphere")
    
    parts = [f"{style_desc}, {mood_desc}"]
    if theme:
        parts.append(f"theme: {theme}")
    prompt = ", ".join(parts)
    audio_bytes, meta = clients.generate_music(
        prompt=prompt, lyrics=lyrics, duration_sec=duration_sec
    )
    out = config.AUDIO_DIR / clients.new_filename(".mp3")
    out.write_bytes(audio_bytes)
    return out, meta


# ---------------------------------------------------------------------------
# 3. Cover art (FLUX, port 9006) — prompt by Qwen
# ---------------------------------------------------------------------------

# Keywords that mark structurally important lyric lines (verses/chorus/refrain).
_IMPORTANT_LINE_RE = re.compile(r"^(?:verse|chorus|refrain|bridge|harp|guitar|\[intro\]|\[outro\]|\[instrumental\]).*:", re.IGNORECASE)


def _select_key_lines(lyrics: str, count: int = 6) -> list[str]:
    """Pick up to *count* lyric lines that carry the song's imagery/mood."""
    lines = [l.strip() for l in lyrics.splitlines() if l.strip()]
    scored: list[tuple[float, str]] = []
    section_idx = 0
    for line in lines:
        score = 0.0
        # Lines right after section headers get priority
        if _IMPORTANT_LINE_RE.match(line):
            score = 10.0 + section_idx * 0.5
            section_idx += 1
        # Short, vivid lines are good lyrical content
        elif 5 <= len(line) <= 120 and not any(
            tag in line.lower() for tag in ("[intro]", "[outro]", "[end]")
        ):
            score = 1.0
        scored.append((score, line))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [line for _, line in scored[:count]]


def cover_prompt_for(song: Song, *, custom_prompt: str | None = None) -> str:
    """Qwen writes a FLUX-safe prompt for this song's cover.

    If *custom_prompt* is given, the user has already written/edited the
    description and we skip Qwen entirely, returning it verbatim.
    """
    if custom_prompt and custom_prompt.strip():
        return custom_prompt.strip()

    # Build the user-side prompt with selected lyric excerpts.
    theme_or_none = (song.theme or "none").strip()
    lyrics_section = prompts.LYRICS_SECTION_EMPTY
    if song.lyrics:
        key_lines = _select_key_lines(song.lyrics, count=6)
        if key_lines:
            lyrics_text = "\n".join(key_lines)
            lyrics_section = prompts.LYRICS_SECTION_FULL.format(
                lyrics_important_lines=lyrics_text
            )

    user = prompts.COVER_USER_TEMPLATE.format(
        title=song.title,
        style=song.style,
        mood=song.mood,
        theme_or_none=theme_or_none,
        lyrics_section=lyrics_section,
    )
    text = clients.qwen_chat_with_fallback(prompts.COVER_SYSTEM, user, max_tokens=1024)
    if not text:
        raise PipelineError("Could not write a cover prompt — please try again.")
    # strip wrapping quotes the model sometimes adds
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return text.strip()


def generate_cover(song: Song, *, custom_prompt: str | None = None) -> tuple[Path, str]:
    """Generate cover PNG for the song. Returns (absolute_path, prompt_used)."""
    prompt = cover_prompt_for(song, custom_prompt=custom_prompt)
    png = clients.generate_image(prompt)
    out = config.COVER_DIR / clients.new_filename(".png")
    out.write_bytes(png)
    return out, prompt


def placeholder_cover() -> Path:
    """Local placeholder (generated once, never committed; not bundled art)."""
    target = config.COVER_DIR / "placeholder.png"
    if not target.exists():
        target.write_bytes(clients.make_placeholder_cover())
    return target


def cover_display_path(song: Song) -> Path:
    cover = song.abs_cover
    if cover is not None and cover.exists():
        return cover
    return placeholder_cover()


# ---------------------------------------------------------------------------
# 4. DJ commentary + speech (Qwen 9001 + Chatterbox 9008)
# ---------------------------------------------------------------------------
def dj_commentary(prev: Song, nxt: Song) -> str:
    user = prompts.DJ_USER.format(
        prev_title=prev.title, prev_style=prev.style, prev_mood=prev.mood,
        prev_theme=prev.theme or "no theme",
        nxt_title=nxt.title, nxt_style=nxt.style, nxt_mood=nxt.mood,
        nxt_theme=nxt.theme or "no theme",
    )
    text = clients.qwen_chat_with_fallback(prompts.DJ_SYSTEM, user, max_tokens=1024)
    if not text:
        raise PipelineError("Could not write DJ commentary.")
    return text.strip()


def render_dj_clip(text: str, voice_ref: Path | None = None) -> bytes:
    """Chatterbox reads the commentary. Returns MP3 bytes."""
    ref_b64 = None
    if voice_ref is not None and voice_ref.exists():
        ref_b64 = clients.encode_ref_audio(voice_ref.read_bytes())
    return clients.speak(text, ref_audio_b64=ref_b64)


# ---------------------------------------------------------------------------
# 5. Custom-voice validation
# ---------------------------------------------------------------------------
VALID_VOICE_EXTS = {".mp3", ".wav"}


def validate_voice_file(path: str) -> tuple[bool, str]:
    """Check extension and size for a user voice reference (MP3/WAV only)."""
    p = Path(path)
    if p.suffix.lower() not in VALID_VOICE_EXTS:
        return False, "Voice reference must be an MP3 or WAV file."
    size = p.stat().st_size
    if size <= 0:
        return False, "The uploaded voice reference is empty."
    if size > config.VOICE_MAX_BYTES:
        return False, (
            f"Voice reference is {size / 1e6:.1f} MB — the limit is "
            f"{config.VOICE_MAX_BYTES / 1e6:.0f} MB."
        )
    return True, f"{size / 1e6:.1f} MB"


# ---------------------------------------------------------------------------
# 6. Prefetched DJ clips, cached per song pair for the session
# ---------------------------------------------------------------------------
_DJ_CACHE: dict[tuple, dict] = {}   # (prev_id, nxt_id, voice_fp) -> {"clip": rel-or-"", "text": str}
_DJ_EVENTS: dict[tuple, threading.Event] = {}
_DJ_LOCK = threading.Lock()


def prefetch_dj_clip(prev: Song, nxt: Song, voice_fp: str, voice_ref: Path | None) -> None:
    """Start a background thread generating the DJ clip for (prev -> nxt).

    Safe to call repeatedly: one generation per (pair, voice) per session.
    """
    key = (prev.id, nxt.id, voice_fp)
    with _DJ_LOCK:
        if key in _DJ_CACHE or key in _DJ_EVENTS:
            return
        event = threading.Event()
        _DJ_EVENTS[key] = event
    threading.Thread(
        target=_dj_worker, args=(key, prev, nxt, voice_ref, event), daemon=True
    ).start()


def _dj_worker(key: tuple, prev: Song, nxt: Song, voice_ref: Path | None, event: threading.Event) -> None:
    result = {"clip": "", "text": ""}
    try:
        text = dj_commentary(prev, nxt)
        audio = render_dj_clip(text, voice_ref)
        path = config.DJ_DIR / clients.new_filename(".mp3")
        path.write_bytes(audio)
        result = {"clip": str(path.relative_to(config.ROOT)), "text": text}
    except Exception as exc:  # noqa: BLE001 - any failure just skips the commentary
        log.warning("DJ prefetch failed for pair %s: %s", key[:2], exc)
    finally:
        with _DJ_LOCK:
            _DJ_CACHE[key] = result
        event.set()


def wait_dj_clip(
    prev: Song,
    nxt: Song,
    voice_fp: str,
    voice_ref: Path | None,
    timeout: float = config.DJ_WAIT_FOR_PREFETCH,
) -> tuple[Path | None, str | None]:
    """Wait for the prefetched clip; returns (path, text) or (None, None).

    Registers a prefetch if none is in flight (e.g. the queue was edited).
    """
    key = (prev.id, nxt.id, voice_fp)
    with _DJ_LOCK:
        cached = _DJ_CACHE.get(key)
        if cached is not None:
            if not cached.get("clip"):
                return None, None
            return config.ROOT / cached["clip"], cached.get("text")
        event = _DJ_EVENTS.get(key)
        if event is None:
            event = threading.Event()
            _DJ_EVENTS[key] = event
            threading.Thread(
                target=_dj_worker, args=(key, prev, nxt, voice_ref, event), daemon=True
            ).start()
    event.wait(timeout=timeout)
    with _DJ_LOCK:
        cached = _DJ_CACHE.get(key)
    if cached is None or not cached.get("clip"):
        return None, None
    return config.ROOT / cached["clip"], cached.get("text")
