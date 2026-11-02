"""High-level orchestration for the AI Jukebox.

Each pipeline step calls a verified class service (see clients.py) and never
calls out to any paid or third-party service.
"""
from __future__ import annotations

import logging
import re
import subprocess
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


def _norm_title(t: str) -> str:
    """Lowercased, punctuation-stripped title for duplicate/near-duplicate check."""
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()


def _title_used(title: str, existing_titles) -> bool:
    """True if *title* equals or near-repeats an existing title (same normalized
    text, contained in one another, or sharing the first 12 characters — e.g.
    'Sunlight Spills On The Pavement' vs 'Sunlight Spilled on Lemonade')."""
    n = _norm_title(title)
    if not n:
        return False
    for other in existing_titles:
        m = _norm_title(other)
        if m and (m == n or n in m or m in n or n[:12] == m[:12]):
            return True
    return False


def write_song_draft(
    style: str, mood: str, duration_sec: float, instrumental: bool, theme: str,
    *,
    existing_titles: tuple[str, ...] = (),
) -> dict:
    """Return {"title": str, "lyrics": str}. Lyrics is "" for instrumentals."""
    theme = (theme or "").strip()
    duration_sec = max(config.DURATION_MIN, min(float(duration_sec), config.DURATION_MAX))

    kind = "instrumental" if instrumental else "vocal"
    avoid = ""
    if existing_titles:
        avoid = ("Do NOT reuse or near-repeat any of these existing titles: "
                 + ", ".join(existing_titles[:20]) + ".\n")
    title_user = prompts.TITLE_USER.format(style=style, mood=mood,
                                           theme=theme or "none", kind=kind, avoid=avoid)
    title = clients.qwen_chat_with_fallback(
        prompts.TITLE_SYSTEM, title_user, max_tokens=2048,
        temperature=config.CREATIVE_TEMPERATURE,
        fallback_truncations=(60,),
    )
    title = _clean_title(title)
    # If a duplicate still slips through, push back once.
    if title and _title_used(title, existing_titles):
        retry = _clean_title(clients.qwen_chat_with_fallback(
            prompts.TITLE_SYSTEM,
            title_user + "\nYour previous suggestion was already used in this library. "
                         "Pick a completely different title.",
            max_tokens=2048, temperature=config.CREATIVE_TEMPERATURE,
            fallback_truncations=(60,),
        ))
        if retry and not _title_used(retry, existing_titles):
            title = retry
    if not title:
        raise PipelineError("Could not write a song title — please try again.")
    if instrumental:
        return {"title": title, "lyrics": ""}

    # Duration-aware budget: ACE-Step sings what fits the duration, so short
    # songs get a small per-second budget and few sections (a full
    # [Intro]/[Verse 1]/[Chorus]/[Verse 2]/[Bridge]/[Outro] structure simply
    # does not get sung in 10-20 s — only the first lines do).
    if duration_sec <= 20:
        ratio, words = 1.3, max(10, int(duration_sec * 1.3))
        sections = ("For short songs use ONLY [Verse 1], plus a brief [Chorus] if it fits. "
                    "NO [Intro], [Verse 2], [Bridge], or [Outro] — they will not be sung.")
    elif duration_sec <= 45:
        ratio, words = 1.4, max(14, int(duration_sec * 1.4))
        sections = ("Use [Verse 1], [Chorus], and end with the SAME [Chorus] written out "
                    "verbatim again (a chorus must appear twice; the repeat closes the song). "
                    "No [Intro], [Verse 2], [Bridge], or [Outro].")
    else:
        ratio, words = 1.6, max(24, int(duration_sec * 1.6))
        sections = ("Use [Verse 1], [Chorus], [Verse 2], the SAME [Chorus] verbatim once more, "
                    "and a short [Outro]. Skip [Intro] and [Bridge].")
    lyrics = clients.qwen_chat_with_fallback(
        prompts.LYRICS_SYSTEM.format(dur=int(duration_sec), words=words,
                                     sections=sections, ratio=ratio),
        prompts.LYRICS_USER.format(style=style, mood=mood, theme=theme or "none",
                                   dur=int(duration_sec)),
        max_tokens=2048,
        temperature=config.CREATIVE_TEMPERATURE,
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


def cover_prompt_for(
    song: Song, *, custom_prompt: str | None = None,
    user_description: str = "", artistic_style: str = "Illustration",
    color_palette: str = "",
) -> str:
    """Qwen writes a FLUX-safe prompt for this song's cover.

    If *custom_prompt* is given, the user has already written/edited the
    description and we skip Qwen entirely, returning it verbatim.
    """
    if custom_prompt and custom_prompt.strip():
        return custom_prompt.strip()

    medium = {
        "Photo": "Photographic treatment with natural materials, realistic lighting and lens-based composition; not drawn art.",
        "Illustration": "Drawn or painted artwork with expressive illustrative marks and designed shapes; not a photographic image.",
        "Minimal": "Simplified forms, limited detail, a restrained palette and intentional negative space; no dense textures or decorative clutter.",
        "Abstract": "Nonliteral visual metaphor made of expressive shapes, color fields and rhythmic forms rather than a representational scene.",
    }.get(artistic_style, "Preserve the selected artistic style.")
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
    user += (
        "\nExplicit user description (honor all visual choices): " + (user_description.strip() or "none")
        + "\nSelected artistic style: " + (artistic_style.strip() or "Illustration")
        + "\nMedium requirements: " + medium
        + "\nExplicit color palette: " + (color_palette.strip() or "choose a coordinated palette for the song")
    )
    text = clients.qwen_chat_with_fallback(prompts.COVER_SYSTEM, user, max_tokens=1024,
                                           temperature=0.5)
    if not text or not text.strip():
        raise PipelineError("Could not write a cover prompt — please try again.")
    # strip wrapping quotes the model sometimes adds
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    constraints = (
        f" Artistic style: {artistic_style.strip() or 'Illustration'}. {medium}"
        + (f" Color palette: {color_palette.strip()}." if color_palette.strip() else "")
        + " Square album artwork, one clear focal point recognizable at thumbnail size."
        + " No lettering, logos, signatures, or watermarks. The title is displayed separately in the app."
    )
    return text.strip() + constraints


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
def resolve_character(character: str | None) -> str:
    """Return a valid non-""off"" character id.

    The app routes "off" around the DJ pipeline entirely (no commentary, no
    prefetch); if an "off"/unknown value ever reaches a render path anyway,
    it safely falls back to the default character instead of crashing the
    queue.
    """
    if character in prompts.DJ_CHARACTERS and character != "off":
        return character
    return prompts.DJ_DEFAULT_CHARACTER


def dj_commentary(prev: Song, nxt: Song, character: str = prompts.DJ_DEFAULT_CHARACTER) -> str:
    cid = resolve_character(character)
    system = prompts.DJ_SYSTEM.format(persona=prompts.DJ_CHARACTERS[cid]["persona"])
    user = prompts.DJ_USER.format(
        prev_title=prev.title, prev_style=prev.style, prev_mood=prev.mood,
        prev_theme=prev.theme or "no theme",
        nxt_title=nxt.title, nxt_style=nxt.style, nxt_mood=nxt.mood,
        nxt_theme=nxt.theme or "no theme",
    )
    text = clients.qwen_chat_with_fallback(system, user, max_tokens=1024)
    if not text:
        raise PipelineError("Could not write DJ commentary.")
    return text.strip()


def render_dj_clip(
    text: str,
    voice_ref: Path | None = None,
    character: str = prompts.DJ_DEFAULT_CHARACTER,
) -> bytes:
    """Chatterbox reads the commentary. Returns MP3 bytes.

    The character's speed/exaggeration are applied here; the voice is the
    bundled default unless a user voice reference is provided.
    """
    cid = resolve_character(character)
    params = prompts.DJ_CHARACTERS[cid]
    ref_b64 = None
    if voice_ref is not None and voice_ref.exists():
        ref_b64 = clients.encode_ref_audio(voice_ref.read_bytes())
    return clients.speak(
        text, ref_audio_b64=ref_b64,
        speed=params["speed"], exaggeration=params["exaggeration"],
    )


# ---------------------------------------------------------------------------
# 5. Custom-voice validation
# ---------------------------------------------------------------------------
VALID_VOICE_EXTS = {".mp3", ".wav"}


def _find_ffprobe() -> str | None:
    """Try to locate ffprobe; return path or None if not available."""
    for candidate in ("ffprobe", "ffmpeg"):
        try:
            subprocess.run([candidate, "-version"], capture_output=True, timeout=5)
            return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


FFPROBE_BIN = _find_ffprobe()


def _check_voice_duration(path: Path) -> tuple[bool, str]:
    """Return (ok, message) after checking voice file duration with ffprobe/ffmpeg.
    
    Rejects references longer than 60 seconds or shorter than 3 seconds.
    Skips the check entirely if ffprobe is not installed.
    """
    if FFPROBE_BIN is None:
        return True, ""  # ffprobe missing — skip gracefully
    
    try:
        import re as _re
        result = subprocess.run(
            [FFPROBE_BIN, "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        # Duration appears in stderr as "Duration: HH:MM:SS.mmm"
        stderr = result.stderr.lower()
        m = _re.search(r"duration:\s*(\d+):(\d+):(\d+)\.(\d+)", stderr)
        if m:
            total_sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000
        else:
            return True, ""  # can't parse — don't block
        
        if total_sec > 60:
            return False, "Voice reference must be between 3 and 60 seconds long."
        if total_sec < 3:
            return False, "Voice reference must be between 3 and 60 seconds long."
        return True, ""
    except (subprocess.SubprocessError, FileNotFoundError, ValueError):
        return True, ""  # ffprobe failed — skip gracefully


def validate_voice_file(path: str) -> tuple[bool, str]:
    """Check extension and size for a user voice reference (MP3/WAV only)."""
    p = Path(path)
    ext = p.suffix.lower()

    # Already a supported format — just validate
    if ext in VALID_VOICE_EXTS:
        size = p.stat().st_size
        if size <= 0:
            return False, "The uploaded voice reference is empty."
        if size > config.VOICE_MAX_BYTES:
            return False, (
                f"Voice reference is {size / (1024 * 1024):.1f} MB — the limit is "
                f"{config.VOICE_MAX_BYTES / (1024 * 1024):.0f} MB."
            )
        ok, dur_msg = _check_voice_duration(p)
        if not ok:
            return False, dur_msg
        return True, f"{size / (1024 * 1024):.1f} MB"

    # Unsupported format entirely
    return False, f"'{ext}' is not a supported format. Only MP3 or WAV voice files work."


# ---------------------------------------------------------------------------
# 6. Prefetched DJ clips, cached per (song pair, voice, character) for the session
# ---------------------------------------------------------------------------
_DJ_CACHE: dict[tuple, dict] = {}   # (prev_id, nxt_id, voice_fp, character) -> {"clip": rel-or-"", "text": str}
_DJ_EVENTS: dict[tuple, threading.Event] = {}
_DJ_LOCK = threading.Lock()


def _dj_key(prev: Song, nxt: Song, voice_fp: str, character: str) -> tuple:
    return (prev.id, nxt.id, voice_fp, resolve_character(character))


def dj_cache_entry(prev: Song, nxt: Song, voice_fp: str, character: str) -> dict:
    """Read-only view of the cached result for (prev -> nxt, voice, character)."""
    with _DJ_LOCK:
        return dict(_DJ_CACHE.get(_dj_key(prev, nxt, voice_fp, character), {}) or {})


def prefetch_dj_clip(prev: Song, nxt: Song, voice_fp: str, voice_ref: Path | None,
                     character: str = prompts.DJ_DEFAULT_CHARACTER) -> None:
    """Start a background thread generating the DJ clip for (prev -> nxt).

    Safe to call repeatedly: one generation per (pair, voice, character) per
    session. The character is part of the cache key, so switching characters
    generates fresh commentary and a new clip.
    """
    key = _dj_key(prev, nxt, voice_fp, character)
    with _DJ_LOCK:
        if key in _DJ_CACHE or key in _DJ_EVENTS:
            return
        event = threading.Event()
        _DJ_EVENTS[key] = event
    threading.Thread(
        target=_dj_worker, args=(key, prev, nxt, voice_ref, character, event), daemon=True
    ).start()


def _dj_worker(key: tuple, prev: Song, nxt: Song, voice_ref: Path | None,
               character: str, event: threading.Event) -> None:
    result = {"clip": "", "text": ""}
    error_reason = ""
    try:
        text = dj_commentary(prev, nxt, character)
        audio = render_dj_clip(text, voice_ref, character)
        path = config.DJ_DIR / clients.new_filename(".mp3")
        path.write_bytes(audio)
        result = {"clip": str(path.relative_to(config.ROOT)), "text": text}
    except Exception as exc:  # noqa: BLE001
        log.warning("DJ prefetch failed for pair %s: %s", key[:2], exc)
        if voice_ref is not None:
            # Custom voice was requested — fall back to default voice on any failure
            log.info("Custom voice rendering failed — falling back to default voice for %s -> %s", key[0][:8], key[1][:8])
            try:
                text = dj_commentary(prev, nxt, character)
                audio = render_dj_clip(text, voice_ref=None, character=character)
                path = config.DJ_DIR / clients.new_filename(".mp3")
                path.write_bytes(audio)
                result = {"clip": str(path.relative_to(config.ROOT)), "text": text, "_fallback": True}
            except Exception as retry_exc:
                error_reason = f"Fallback also failed: {retry_exc}"
        else:
            error_reason = str(exc)[:200]
    finally:
        with _DJ_LOCK:
            _DJ_CACHE[key] = {**result, "_error": error_reason}
        event.set()


def wait_dj_clip(
    prev: Song,
    nxt: Song,
    voice_fp: str,
    voice_ref: Path | None,
    character: str = prompts.DJ_DEFAULT_CHARACTER,
    timeout: float = config.DJ_WAIT_FOR_PREFETCH,
) -> tuple[Path | None, str | None, str]:
    """Wait for the prefetched clip; returns (path, text, error_reason).

    * error_reason == ''           → success (clip is valid path)
    * error_reason == 'voice'      → custom voice rejected; fallback succeeded
    * error_reason == 'service'    → service unavailable / generic failure
    Returns (None, None, reason) on complete failure.
    """
    key = _dj_key(prev, nxt, voice_fp, character)
    with _DJ_LOCK:
        cached = _DJ_CACHE.get(key)
        if cached is not None:
            clip_path = cached.get("clip")
            if not clip_path:
                return None, None, "service"
            return config.ROOT / clip_path, cached.get("text"), ""
        event = _DJ_EVENTS.get(key)
        if event is None:
            event = threading.Event()
            _DJ_EVENTS[key] = event
            threading.Thread(
                target=_dj_worker, args=(key, prev, nxt, voice_ref, character, event), daemon=True
            ).start()
    event.wait(timeout=timeout)
    with _DJ_LOCK:
        cached = _DJ_CACHE.get(key)
    if cached is None:
        return None, None, "service"
    clip_path = cached.get("clip")
    if not clip_path:
        reason = "voice" if "_fallback" in cached else "service"
        return None, None, reason
    # Fallback succeeded — custom voice was rejected but default voice produced a clip
    if cached.get("_fallback"):
        return config.ROOT / clip_path, cached.get("text"), "voice"
    return config.ROOT / clip_path, cached.get("text"), ""
