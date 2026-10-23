"""AI Jukebox — Gradio app. One-command launch: ``python app.py``.

Features
--------
1. Custom song generation (Qwen lyrics/title -> ACE-Step music -> FLUX cover).
2. Matching cover art, with placeholder + retry when generation fails.
3. AI DJ commentary between queued songs (Qwen -> Chatterbox), prefetched and
   cached per song pair; optional custom voice (MP3/WAV, gitignored).
4. Single gr.Audio player driven by a sequential state machine
   (song -> DJ clip -> song -> ...) stored in gr.State and advanced on the
   audio component's ``end`` event.
"""
from __future__ import annotations

import html
import logging
import shutil
import time
from pathlib import Path
from urllib.parse import quote

import gradio as gr

from jukebox import clients, config, service
from jukebox.library import Song, SongLibrary

config.setup_logging()
config.check_config()

log = logging.getLogger("jukebox.app")

LIBRARY = SongLibrary()

# ---------------------------------------------------------------------------
# UI constants
# ---------------------------------------------------------------------------
GENRES = [
    "Pop", "Rock", "Hip-hop", "R&B / Soul", "Electronic / EDM", "Jazz",
    "Blues", "Country", "Folk", "Classical", "Reggae", "Lo-fi", "Metal",
    "Cinematic", "K-pop", "Latin",
]
MOODS = ["Happy", "Energetic", "Calm", "Melancholic", "Dreamy", "Dark",
         "Romantic", "Epic", "Whimsical", "Nostalgic"]

INITIAL_PLAYER = {"queue": [], "pos": 0, "mode": "idle"}

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _elapsed(started: float) -> str:
    sec = int(time.monotonic() - started)
    return f"{sec // 60}:{sec % 60:02d}"


def _serve_url(p: Path) -> str:
    """Same-origin URL for a repo file (works inside gr.HTML)."""
    return f"/gradio_api/file={quote(str(p))}"


def _voice_fp(voice_state: dict) -> str:
    return str(voice_state.get("path", "default"))


def _voice_ref(voice_state: dict) -> Path | None:
    p = voice_state.get("path")
    if not p:
        return None
    path = Path(p)
    return path if path.exists() else None


def _library_views() -> tuple[list, list]:
    songs = LIBRARY.all()
    items = [
        (str(service.cover_display_path(s)), f"{s.title} · {s.style} · {s.mood}")
        for s in songs
    ]
    # Gradio 6 requires (label, value) tuples; dicts are interpreted key-only.
    choices = [(s.display_label(), s.id) for s in songs]
    return items, choices


def _queue_html(state: dict) -> str:
    queue, pos, mode = state["queue"], state["pos"], state["mode"]
    if not queue:
        return "<p style='color:#64748b; text-align:center; padding:20px;'><i>🎵 Queue is empty — generate a song or press Play all.</i></p>"
    rows = []
    for i, sid in enumerate(queue):
        song = LIBRARY.get(sid)
        if song is None:
            continue
        is_current = i == pos and mode in ("song", "dj")
        icon = "▶️" if is_current and mode == "song" else ("🎙️" if is_current else "·")
        marker = "" if is_current else ""
        bg = "linear-gradient(135deg, rgba(139,92,246,0.12), rgba(96,165,250,0.1))" if is_current else "rgba(255,255,255,0.02)"
        border_color = "rgba(139,92,246,0.3)" if is_current else "rgba(255,255,255,0.06)"
        title = html.escape(song.title)
        credit = ""
        if song.created_by.strip():
            credit = f'<span style="color:#7aadd;font-size:11px;display:block;margin-top:2px">by {html.escape(song.created_by)}</span>'
        meta = f'{html.escape(song.style)} · {html.escape(song.mood)} · {"instrumental" if song.instrumental else "vocal"}'
        cover_url = _serve_url(service.cover_display_path(song))
        rows.append(
            f"<div style='background:{bg};border:1px solid {border_color};"
            f"border-radius:10px;padding:8px 12px;margin:6px 0;flex-shrink:0;'>"
            f"<div style='display:flex;align-items:center;gap:12px;'> "
            f"<img src='{cover_url}' style='width:44px;height:44px;border-radius:8px;object-fit:cover;'/>"
            f"<div><b style='color:#e2e8f0'>{icon} {marker}{title}</b>{credit}"
            f"<span style='color:#64748b;font-size:11px'>{meta}</span></div></div></div>"
        )
    return "<div style='display:flex;flex-direction:column;gap:4px;'>\n" + "\n".join(rows) + "\n</div>"


def _now_status(song: Song, mode: str) -> str:
    kind = "instrumental" if song.instrumental else "vocal"
    state = "**Now playing:**" if mode == "song" else "**Up next:**"
    return f"{state} {song.title} — {song.style} · {song.mood} ({kind})"


def _spawn_prefetch(state: dict, song: Song, voice_state: dict) -> None:
    nxt_i = state["pos"] + 1
    if nxt_i < len(state["queue"]):
        nxt = LIBRARY.get(state["queue"][nxt_i])
        if nxt is not None:
            service.prefetch_dj_clip(song, nxt, _voice_fp(voice_state), _voice_ref(voice_state))


# ---------------------------------------------------------------------------
# state machine
# ---------------------------------------------------------------------------
def _start_song(state: dict, idx: int, voice_state: dict) -> tuple:
    state["pos"], state["mode"] = idx, "song"
    song = LIBRARY.get(state["queue"][idx])
    if song is None:
        state["mode"] = "idle"
        return _queue_html(state), "That song is no longer in the library.", gr.update(), gr.update(value=None), gr.update(interactive=False), state
    _spawn_prefetch(state, song, voice_state)
    return (
        _queue_html(state),
        _now_status(song, "song"),
        gr.update(value=str(service.cover_display_path(song))),
        gr.update(value=str(song.abs_audio)),
        gr.update(interactive=True),
        state,
    )


def advance(player_state: dict, voice_state: dict) -> tuple:
    """Called by the player's `end` event and by Skip.

    song -> DJ clip -> next song -> ... ; state machine lives in gr.State.
    """
    state = dict(player_state)
    if state["mode"] == "idle":
        return _queue_html(state), "Nothing is playing.", gr.update(), gr.update(), gr.update(interactive=False), state

    if state["mode"] == "song":
        nxt_i = state["pos"] + 1
        if nxt_i >= len(state["queue"]):
            state["mode"] = "idle"
            return (
                _queue_html(state),
                "🏁 Queue finished — thanks for listening!",
                gr.update(), gr.update(value=None), gr.update(interactive=False), state,
            )
        prev, nxt = LIBRARY.get(state["queue"][state["pos"]]), LIBRARY.get(state["queue"][nxt_i])
        if prev is None or nxt is None:
            return _start_song(state, nxt_i, voice_state)
        clip, text = service.wait_dj_clip(prev, nxt, _voice_fp(voice_state), _voice_ref(voice_state))
        if clip is not None:
            state["mode"] = "dj"
            return (
                _queue_html(state),
                f"🎙️ **DJ:** {html.escape(text or '')}",
                gr.update(), gr.update(value=str(clip)), gr.update(interactive=True), state,
            )
        gr.Info("DJ commentary is unavailable right now — skipping to the next song.")
        return _start_song(state, nxt_i, voice_state)

    # mode == "dj": clip finished -> next song
    nxt_i = state["pos"] + 1
    if nxt_i >= len(state["queue"]):
        state["mode"] = "idle"
        return (
            _queue_html(state),
            "🏁 Queue finished — thanks for listening!",
            gr.update(), gr.update(value=None), gr.update(interactive=False), state,
        )
    return _start_song(state, nxt_i, voice_state)


def skip(player_state: dict, voice_state: dict) -> tuple:
    return advance(player_state, voice_state)


def play(player_state: dict, voice_state: dict) -> tuple:
    state = dict(player_state)
    if state["mode"] != "idle":
        state["mode"], state["pos"] = "song", max(0, state["pos"])
    elif not state["queue"]:
        state["queue"] = [s.id for s in LIBRARY.all()]
        state["pos"] = 0
    if not state["queue"]:
        return (
            _queue_html(state),
            "The library is empty — generate a song first.",
            gr.update(), gr.update(), gr.update(interactive=False), state,
        )
    return _start_song(state, state["pos"], voice_state)


def play_all(player_state: dict, voice_state: dict) -> tuple:
    songs = [s.id for s in LIBRARY.all()]
    if not songs:
        return (
            _queue_html(dict(player_state)),
            "The library is empty — generate a song first.",
            gr.update(), gr.update(), gr.update(interactive=False), dict(player_state),
        )
    state = {"queue": songs, "pos": 0, "mode": "idle"}
    return play(state, voice_state)


def add_to_queue(song_id: str, player_state: dict) -> tuple:
    state = dict(player_state)
    if not song_id:
        return _queue_html(state), "Select a song in the Library tab first."
    song = LIBRARY.get(song_id)
    if song is None:
        return _queue_html(state), "That song no longer exists."
    state["queue"].append(song_id)
    return _queue_html(state), f"➕ Added “{song.title}” to the queue.", state


# ---------------------------------------------------------------------------
# generation pipeline
# ---------------------------------------------------------------------------
def generate_song(created_by: str, style: str, mood: str, duration: float, instrumental: bool, theme: str):
    started = time.monotonic()
    status = lambda msg: f"{msg} · elapsed {_elapsed(started)}"
    noop_gallery, noop_pick = gr.update(), gr.update()

    yield gr.update(interactive=False), status("✍️ Writing title and lyrics…"), "", noop_gallery, noop_pick
    try:
        duration = max(config.DURATION_MIN, min(float(duration), config.DURATION_MAX))

        draft = service.write_song_draft(style, mood, duration, instrumental, theme)
        yield (gr.update(interactive=False),
               status(f"🎵 Composing “{draft['title']}” (ACE-Step is working — this can take a minute)…"),
               "", noop_gallery, noop_pick)

        audio_path, meta = service.compose_music(style, mood, theme or "", duration, draft["lyrics"])
        yield (gr.update(interactive=False),
               status("🎨 Painting cover art (FLUX)…"), "", noop_gallery, noop_pick)

        cover_rel = None
        cover_prmpt = ""
        try:
            tmp = Song(
                id="", title=draft["title"], style=style, mood=mood,
                duration_sec=duration, instrumental=instrumental,
                theme=(theme or "").strip(), lyrics=draft["lyrics"],
            )
            cover_abs, cover_prmpt = service.generate_cover(tmp)
            cover_rel = str(cover_abs.relative_to(config.ROOT))
        except Exception as exc:  # noqa: BLE001 - cover failure is non-fatal
            log.warning("Cover generation failed: %s", exc)
            service.placeholder_cover()

        song = LIBRARY.add(
            title=draft["title"], style=style, mood=mood, duration_sec=duration,
            instrumental=instrumental, theme=(theme or "").strip(),
            lyrics=draft["lyrics"], created_by=created_by.strip(),
            audio_path=str(audio_path.relative_to(config.ROOT)),
            cover_path=cover_rel,
            cover_prompt=cover_prmpt if cover_rel else "",
        )
        if cover_rel is None:
            note = "⚠️ Cover could not be generated — use **Retry cover**."
        elif meta:
            note = f"BPM {meta.get('bpm', '?')} · {meta.get('timesignature', '?')}/4"
        else:
            note = ""
        creator_tag = f"\n_Created by {html.escape(created_by)}_" if created_by.strip() else ""
        result = (
            f"### ✅ \u201c{html.escape(song.title)}\u201d saved to the library{creator_tag}\n"
            f"*{html.escape(song.style)} · {html.escape(song.mood)} · "
            f"{'instrumental' if song.instrumental else 'vocal'} · "
            f"{int(duration)}s* · {note}\n\n"
        )
        if song.lyrics:
            result += f"**Lyrics** ({len(song.lyrics.splitlines())} lines):\n\n```\n{song.lyrics}\n```"
        else:
            result += "_Instrumental track — no lyrics._"
        items, choices = _library_views()
        yield (gr.update(interactive=True),
               status("✅ Song generated and added to the library."),
               result,
               gr.update(value=items), gr.update(choices=choices, value=song.id))
    except Exception as exc:  # noqa: BLE001 - surface any pipeline failure in the UI
        log.exception("Song generation failed")
        yield (gr.update(interactive=True),
               status(f"❌ Generation failed: {exc}"), "", noop_gallery, noop_pick)


def retry_cover(
    song_id: str, player_state: dict, cover_description: str | None = None,
):
    """Regenerate cover; honour *cover_description* if the user edited it."""
    if not song_id:
        return (gr.update(),
                "Use the Library tab to select a song first.", gr.update(), gr.update())
    song = LIBRARY.get(song_id)
    if song is None:
        return gr.update(), "That song no longer exists.", gr.update(), gr.update()

    # Decide whether the caller wants to regenerate or edit the prompt only.
    regen = cover_description and cover_description.strip()
    if not regen:
        return gr.update(), "", gr.update(), gr.update()

    try:
        cover_abs, used_prompt = service.generate_cover(song, custom_prompt=regen)
    except Exception as exc:  # noqa: BLE001
        log.warning("Cover retry failed: %s", exc)
        return (gr.update(),
                f"❌ Cover regeneration failed: {exc}", gr.update(), gr.update())
    LIBRARY.update(
        song_id,
        cover_path=str(cover_abs.relative_to(config.ROOT)),
        cover_prompt=used_prompt,
    )
    items, _ = _library_views()
    state = dict(player_state)
    now_cover = gr.update()
    if state["mode"] in ("song", "dj") and state["queue"]:
        cur = state["queue"][state["pos"]]
        if cur == song_id:
            now_cover = gr.update(value=str(service.cover_display_path(song)))
    return (gr.update(value=items),
            f'✅ New cover saved for "{html.escape(song.title)}".',
            _queue_html(state), now_cover)


# ---------------------------------------------------------------------------
# Delete songs from library
# ---------------------------------------------------------------------------
def delete_song(song_id: str, player_state: dict):
    if not song_id or player_state is None:
        return "", gr.update(), gr.update(value=[]), _queue_html(player_state) if player_state else ""
    song = LIBRARY.get(song_id)
    if song is None:
        return "❌ Song not found.", gr.update(), gr.update(value=[]), ""
    ok = LIBRARY.delete(song_id)
    if not ok:
        return f"❌ Could not delete \"{html.escape(song.title)}\".", gr.update(), gr.update(value=[]), ""
    
    # Remove from queue if present
    if player_state and song_id in player_state.get("queue", []):
        queue = player_state["queue"]
        pos = player_state["pos"]
        if pos >= len(queue):
            pos = max(0, len(queue) - 1)
        player_state["queue"] = [s for s in queue if s != song_id]
        player_state["pos"] = min(pos, len(player_state["queue"]) - 1)
        if not player_state["queue"]:
            player_state["pos"] = -1
    
    items, choices = _library_views()
    return (f'🗑 Deleted "{html.escape(song.title)}".',
            gr.update(choices=choices, value=None),
            gr.update(value=items),          # refresh gallery tiles
            _queue_html(player_state))


# ---------------------------------------------------------------------------
# custom DJ voice
# ---------------------------------------------------------------------------
def on_voice_upload(filepath: str | None, voice_state: dict):
    if not filepath:
        return "Using the default bundled DJ voice.", gr.update(interactive=False), gr.update(), voice_state
    ok, msg = service.validate_voice_file(filepath)
    if not ok:
        return f"❌ {msg}", gr.update(interactive=False), gr.update(value=None), voice_state
    src = Path(filepath)
    dest = config.VOICE_DIR / f"voice_{clients.new_filename(src.suffix)}"
    shutil.copy2(src, dest)
    new_state = {"path": str(dest), "name": src.name}
    return (
        f"✅ Custom DJ voice ready: *{src.name}* ({msg}) — voice cloning enabled.",
        gr.update(interactive=True),
        gr.update(), new_state,
    )


def on_voice_remove(voice_state: dict):
    p = voice_state.get("path")
    if p:
        Path(p).unlink(missing_ok=True)
        log.info("Removed custom voice reference %s", Path(p).name)
    return (
        "🗑 Custom voice removed — back to the default DJ voice.",
        gr.update(interactive=False), gr.update(value=None), {},
    )


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
/* ===================== THEME VARIABLES ===================== */
:root { --transition-speed: 0.3s; }

/* ================= DARK MODE ================= */
main {
    background: linear-gradient(160deg, #181a2b 0%, #1c2040 40%, #162038 100%);
    min-height: 100vh !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    transition: background var(--transition-speed);
}
body, .wrap { background: transparent !important; }

.prose h1, .prose > h1 {
    font-size: 2.2rem !important;
    font-weight: 800 !important;
    background: linear-gradient(135deg, #a78bfa, #60a5fa, #34d399);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0.2em !important;
}
.prose p, .prose > p { color: #8b95c0 !important; font-size: 0.95rem !important; }

.tabitem {
    background: rgba(255,255,255,0.04) !important;
    border-radius: 12px !important;
    border: 1px solid rgba(139,92,246,0.12) !important;
    transition: background var(--transition-speed), border var(--transition-speed);
}
.tab-nav {
    background: rgba(255,255,255,0.04) !important;
    border-radius: 10px !important;
    padding: 4px !important;
}
.tab-nav button.selected {
    background: linear-gradient(135deg, rgba(139,92,246,0.25), rgba(96,165,250,0.25)) !important;
    color: #e0e7ff !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    box-shadow: 0 2px 12px rgba(139,92,246,0.15) !important;
}
.tab-nav button:not(.selected) {
    color: #64748b !important;
    border-radius: 8px !important;
    transition: all 0.2s ease;
}
.tab-nav button:hover:not(.selected) {
    color: #8b95c0 !important;
    background: rgba(255,255,255,0.04) !important;
}

.prose h2, .prose > h2 {
    font-size: 1.15rem !important;
    font-weight: 700 !important;
    color: #b4bcd6 !important;
    margin-top: 0.5em !important;
    margin-bottom: 0.6em !important;
}

label {
    color: #8b95c0 !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
    text-transform: uppercase !important;
    transition: color var(--transition-speed);
}

select, .dropdown-wrap {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 8px !important;
    color: #d4d8ec !important;
    transition: all var(--transition-speed);
}
select:focus, select:hover {
    border-color: rgba(139,92,246,0.5) !important;
    box-shadow: 0 0 0 3px rgba(139,92,246,0.1) !important;
}

input[type="text"], textarea, .textbox-wrap {
    background: rgba(255,255,255,0.07) !important;
    border: 1px solid rgba(139,92,246,0.2) !important;
    border-radius: 8px !important;
    color: #d4d8ec !important;
    transition: all var(--transition-speed);
}
input[type="text"]:focus, textarea:focus {
    border-color: rgba(139,92,246,0.5) !important;
    box-shadow: 0 0 0 3px rgba(139,92,246,0.1) !important;
}

button.primary, .primary .wrap {
    background: linear-gradient(135deg, #7c3aed, #6366f1) !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em !important;
    box-shadow: 0 4px 15px rgba(124,58,237,0.3) !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease !important;
}
button.primary:hover:not(.disabled), .primary .wrap:hover:not(.disabled) {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(124,58,237,0.45) !important;
}

button.secondary {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(139,92,246,0.15) !important;
    border-radius: 10px !important;
    color: #b4bcd6 !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
}
button.secondary:hover {
    background: rgba(255,255,255,0.1) !important;
    border-color: rgba(139,92,246,0.4) !important;
}

.delete-btn {
    background: rgba(239,68,68,0.1) !important;
    border: 1px solid rgba(239,68,68,0.2) !important;
    color: #fca5a5 !important;
    border-radius: 10px !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
}
.delete-btn:hover {
    background: rgba(239,68,68,0.22) !important;
    border-color: rgba(239,68,68,0.5) !important;
    color: #fecaca !important;
}

.checkbox-row {
    background: rgba(255,255,255,0.03) !important;
    border-radius: 8px !important;
    padding: 8px 12px !important;
    border: 1px solid rgba(139,92,246,0.1) !important;
}
checkbox label {
    color: #b4bcd6 !important;
    text-transform: none !important;
    letter-spacing: normal !important;
    font-size: 0.9rem !important;
}

.gallery {
    background: rgba(255,255,255,0.04) !important;
    border-radius: 12px !important;
    border: 1px solid rgba(139,92,246,0.12) !important;
    padding: 8px !important;
    transition: all var(--transition-speed);
}

.slider-container {
    background: rgba(255,255,255,0.03) !important;
    border-radius: 8px !important;
    border: 1px solid rgba(139,92,246,0.1) !important;
}
.slider-container input {
    background: rgba(139,92,246,0.3) !important;
}

.markdown-status-success {
    background: rgba(34,197,94,0.08) !important;
    border: 1px solid rgba(34,197,94,0.2) !important;
    border-radius: 10px !important;
    color: #86efac !important;
    padding: 10px 14px !important;
}
.markdown-status-error {
    background: rgba(239,68,68,0.08) !important;
    border: 1px solid rgba(239,68,68,0.2) !important;
    border-radius: 10px !important;
    color: #fca5a5 !important;
    padding: 10px 14px !important;
}

.audio-player {
    border-radius: 12px !important;
    overflow: hidden !important;
}

[data-testid="image"] {
    border-radius: 12px !important;
    border: 1px solid rgba(139,92,246,0.15) !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3) !important;
    transition: border var(--transition-speed), box-shadow var(--transition-speed);
}

.gradio-column { gap: 20px !important; }

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(139,92,246,0.2); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(139,92,246,0.35); }

.queue-item-current {
    background: linear-gradient(135deg, rgba(139,92,246,0.12), rgba(96,165,250,0.1)) !important;
    border: 1px solid rgba(139,92,246,0.25) !important;
    border-radius: 10px !important;
    box-shadow: 0 2px 10px rgba(139,92,246,0.08) !important;
}

.component-info {
    color: #8b95c0 !important;
    font-size: 0.78rem !important;
    font-style: italic !important;
}

/* ================= LIGHT MODE ================= */
[data-theme="light"] main {
    background: linear-gradient(160deg, #f5f4f1 0%, #edecea 40%, #e8e6e1 100%) !important;
}

[data-theme="light"] .tabitem {
    background: rgba(250,249,247,0.85) !important;
    border: 1px solid rgba(0,0,0,0.06) !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04) !important;
}
[data-theme="light"] .tab-nav {
    background: rgba(0,0,0,0.02) !important;
}
[data-theme="light"] .tab-nav button.selected {
    background: rgba(139,92,246,0.12) !important;
    color: #3a4150 !important;
    box-shadow: 0 2px 8px rgba(139,92,246,0.08) !important;
}
[data-theme="light"] .tab-nav button:not(.selected) {
    color: #6b7488 !important;
}
[data-theme="light"] .tab-nav button:hover:not(.selected) {
    color: #3a4150 !important;
    background: rgba(139,92,246,0.04) !important;
}

[data-theme="light"] .prose h1, [data-theme="light"] .prose > h1 {
    background: linear-gradient(135deg, #7c3aed, #6366f1, #0ea5e9) !important;
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
}
[data-theme="light"] .prose p, [data-theme="light"] .prose > p {
    color: #5a6373 !important;
}
[data-theme="light"] .prose h2, [data-theme="light"] .prose > h2 {
    color: #3a4150 !important;
}

[data-theme="light"] label {
    color: #5a6373 !important;
}

[data-theme="light"] select, [data-theme="light"] .dropdown-wrap {
    background: #faf9f7 !important;
    border: 1px solid rgba(0,0,0,0.1) !important;
    color: #3a4150 !important;
}
[data-theme="light"] select option {
    background: #faf9f7 !important;
    color: #3a4150 !important;
}

[data-theme="light"] input[type="text"],
[data-theme="light"] textarea,
[data-theme="light"] .textbox-wrap {
    background: #faf9f7 !important;
    border: 1px solid rgba(0,0,0,0.1) !important;
    color: #3a4150 !important;
}

[data-theme="light"] checkbox label {
    color: #3a4150 !important;
}

[data-theme="light"] .gallery {
    background: rgba(250,249,247,0.8) !important;
    border: 1px solid rgba(0,0,0,0.06) !important;
}

[data-theme="light"] .slider-container {
    background: rgba(250,249,247,0.8) !important;
}
[data-theme="light"] .slider-container input {
    background: rgba(139,92,246,0.2) !important;
}

[data-theme="light"] button.secondary {
    background: rgba(0,0,0,0.03) !important;
    border: 1px solid rgba(0,0,0,0.08) !important;
    color: #4a5263 !important;
}
[data-theme="light"] button.secondary:hover {
    background: rgba(0,0,0,0.07) !important;
    border-color: rgba(139,92,246,0.3) !important;
}

[data-theme="light"] .delete-btn {
    background: rgba(239,68,68,0.08) !important;
    border: 1px solid rgba(239,68,68,0.2) !important;
    color: #b91c1c !important;
}
[data-theme="light"] .delete-btn:hover {
    background: rgba(239,68,68,0.15) !important;
    border-color: rgba(239,68,68,0.4) !important;
    color: #991b1b !important;
}

[data-theme="light"] .markdown-status-success {
    background: rgba(34,197,94,0.06) !important;
    border: 1px solid rgba(34,197,94,0.2) !important;
    color: #15803d !important;
}
[data-theme="light"] .markdown-status-error {
    background: rgba(239,68,68,0.06) !important;
    border: 1px solid rgba(239,68,68,0.2) !important;
    color: #b91c1c !important;
}

[data-theme="light"] [data-testid="image"] {
    border: 1px solid rgba(0,0,0,0.08) !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.06) !important;
}

[data-theme="light"] ::-webkit-scrollbar-thumb {
    background: rgba(0,0,0,0.12); border-radius: 3px;
}
[data-theme="light"] ::-webkit-scrollbar-thumb:hover {
    background: rgba(0,0,0,0.2);
}

[data-theme="light"] .queue-item-current {
    background: linear-gradient(135deg, rgba(139,92,246,0.08), rgba(96,165,250,0.06)) !important;
    border: 1px solid rgba(139,92,246,0.25) !important;
    box-shadow: 0 2px 10px rgba(139,92,246,0.08) !important;
}

[data-theme="light"] .component-info {
    color: #8b95a0 !important;
}

/* ================= THEME TOGGLE ================= */
.theme-toggle-btn {
    display: inline-flex !important;
    align-items: center; justify-content: center;
    background: transparent !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 10px !important;
    padding: 6px 12px !important;
    font-size: 1.3rem !important;
    cursor: pointer !important;
    transition: all 0.2s ease !important;
    min-width: 44px; height: 44px;
    line-height: 1 !important;
}
.theme-toggle-btn:hover {
    background: rgba(255,255,255,0.08) !important;
    border-color: rgba(139,92,246,0.4) !important;
    transform: scale(1.08);
}
[data-theme="light"] .theme-toggle-btn {
    border-color: rgba(0,0,0,0.12) !important;
    background: rgba(0,0,0,0.04) !important;
}
[data-theme="light"] .theme-toggle-btn:hover {
    background: rgba(0,0,0,0.08) !important;
    border-color: rgba(139,92,246,0.4) !important;
}
"""

# ---- Theme JavaScript (loaded via Gradio's js= parameter) ----
THEME_JS = r"""
(function() {
    window.__toggleTheme = function() {
        var current = document.documentElement.getAttribute('data-theme') || 'dark';
        var next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        try { localStorage.setItem('aj-theme', next); } catch(e) {}
        __applyThemeIcon();
    };
    function __applyThemeIcon() {
        var current = document.documentElement.getAttribute('data-theme') || 'dark';
        var btn = document.getElementById('themeToggle');
        if (!btn) return;
        btn.textContent = current === 'dark' ? '\u2600\ufe0f' : '\ud83c\udf19';
        btn.title = current === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    }
    // Restore saved theme on load
    try {
        var saved = localStorage.getItem('aj-theme');
        if (saved === 'light') {
            document.documentElement.setAttribute('data-theme', 'light');
        } else {
            document.documentElement.setAttribute('data-theme', 'dark');
        }
    } catch(e) {}
    __applyThemeIcon();
    // Attach click handlers to all theme toggle buttons (handles Gradio re-renders)
    function attachToggles() {
        document.querySelectorAll('.theme-toggle').forEach(function(btn) {
            btn.addEventListener('click', window.__toggleTheme);
        });
    }
    attachToggles();
    // Re-observe DOM changes for Gradio dynamic renders
    if (typeof MutationObserver !== 'undefined') {
        var observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(m) {
                if (m.addedNodes.length) attachToggles();
            });
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }
})();
"""

def build_app() -> gr.Blocks:
    with gr.Blocks(title="AI Jukebox") as demo:
        # Header with accent border & theme toggle
        gr.HTML('''
            <div style="display:flex; justify-content:space-between; align-items:center; padding-bottom:20px; border-bottom:1px solid rgba(255,255,255,0.08); margin-bottom:16px;">
                <div>
                    <h1 id="mainTitle" style="margin:0;font-size:2rem;">🎵 AI Jukebox</h1>
                    <p id="mainDesc" style="margin:4px 0 0;color:#94a3b8;font-size:0.95rem;">Generate original songs with matching cover art, and let an AI DJ spin commentary between tracks.</p>
                </div>
                <button class="theme-toggle" id="themeToggle" title="Toggle light / dark mode">☀️</button>
            </div>
        ''')
        player_state = gr.State(INITIAL_PLAYER)
        voice_state = gr.State({})

        with gr.Row():
            # ---------------- left column: create + library ----------------
            with gr.Column(scale=2):
                with gr.Tab("✨ Generate"):
                    with gr.Group():
                        created_by = gr.Textbox("", label="Your name", placeholder="Enter your name for credit")
                        style = gr.Dropdown(GENRES, value="Pop", allow_custom_value=True, label="Genre")
                        mood = gr.Dropdown(MOODS, value="Happy", label="Mood")
                        duration = gr.Slider(config.DURATION_MIN, 60, value=config.DURATION_DEFAULT, step=5, label="Duration (seconds)")
                        instrumental = gr.Checkbox(False, label="Instrumental (no lyrics)")
                        theme = gr.Textbox("", label="Theme (optional)", placeholder="e.g. a robot band playing on the moon")
                        gen_btn = gr.Button("🎵 Generate song", variant="primary")
                    gen_status = gr.Markdown("")
                    gen_result = gr.Markdown("")

                with gr.Tab("📚 Library"):
                    _items, _choices = _library_views()
                    library_gallery = gr.Gallery(value=_items, label="", columns=4, height=320, object_fit="cover")
                    song_pick = gr.Dropdown(_choices, label="Select a song")
                    cover_desc = gr.Textbox("", lines=4, max_lines=8, label="Cover description (edit then Retry)")
                    with gr.Row(variant="compact"):
                        add_queue_btn = gr.Button("➕ Add to queue", size="sm")
                        retry_cover_btn = gr.Button("🖼️ Retry cover", size="sm")
                        delete_song_btn = gr.Button("🗑 Delete", size="sm", variant="stop")
                        play_all_btn = gr.Button("▶️ Play all", size="sm")
                    lib_status = gr.Markdown("")

            # ---------------- right column: player + DJ voice ----------------
            with gr.Column(scale=3):
                gr.Markdown("### 🎧 Now Playing")
                now_cover = gr.Image(label="", height=280, interactive=False)
                now_status = gr.Markdown("Nothing playing — generate a song or press **Play all**.")
                now_audio = gr.Audio(label="", type="filepath", interactive=False, autoplay=True)
                with gr.Row():
                    play_btn = gr.Button("▶️ Play", variant="primary", size="lg")
                    skip_btn = gr.Button("⏭️ Skip", interactive=False, size="lg")
                
                gr.Markdown("### 📋 Queue")
                queue_html = gr.HTML(_queue_html(INITIAL_PLAYER))

                gr.Markdown("### 🎙️ DJ Voice")
                voice_upload = gr.Audio(type="filepath", label="Custom DJ voice (optional MP3/WAV)", sources=["upload"])
                voice_status = gr.Markdown("Using the default bundled DJ voice.")
                remove_voice_btn = gr.Button("Remove custom voice", interactive=False)

        # ---------------- events ----------------
        gen_btn.click(
            generate_song,
            inputs=[created_by, style, mood, duration, instrumental, theme],
            outputs=[gen_btn, gen_status, gen_result, library_gallery, song_pick],
        )
        add_queue_btn.click(
            add_to_queue,
            inputs=[song_pick, player_state],
            outputs=[queue_html, lib_status, player_state],
        )
        play_all_btn.click(
            play_all,
            inputs=[player_state, voice_state],
            outputs=[queue_html, now_status, now_cover, now_audio, skip_btn, player_state],
        )
        play_btn.click(
            play,
            inputs=[player_state, voice_state],
            outputs=[queue_html, now_status, now_cover, now_audio, skip_btn, player_state],
        )
        skip_btn.click(
            skip,
            inputs=[player_state, voice_state],
            outputs=[queue_html, now_status, now_cover, now_audio, skip_btn, player_state],
        )
        # Gradio 6.30 exposes the audio "end" event as `stop`: the player's DOM
        # `ended` event (natural playback finish) is wired to the component's
        # `stop` handler; `pause` is only the user-pause event. Skipping the
        # current track also routes through `advance()` via the Skip button.
        now_audio.stop(
            advance,
            inputs=[player_state, voice_state],
            outputs=[queue_html, now_status, now_cover, now_audio, skip_btn, player_state],
        )
        # When a library song is selected, load its saved cover prompt into the editor.
        def on_song_select(song_id: str):
            if not song_id:
                return ""
            song = LIBRARY.get(song_id)
            if song is None:
                return ""
            return song.cover_prompt or ""
        song_pick.change(
            on_song_select,
            inputs=[song_pick],
            outputs=[cover_desc],
        )
        retry_cover_btn.click(
            retry_cover,
            inputs=[song_pick, player_state, cover_desc],
            outputs=[library_gallery, lib_status, queue_html, now_cover],
        )
        delete_song_btn.click(
            delete_song,
            inputs=[song_pick, player_state],
            outputs=[lib_status, song_pick, library_gallery, queue_html],
        )
        voice_upload.change(
            on_voice_upload,
            inputs=[voice_upload, voice_state],
            outputs=[voice_status, remove_voice_btn, voice_upload, voice_state],
        )
        remove_voice_btn.click(
            on_voice_remove,
            inputs=[voice_state],
            outputs=[voice_status, remove_voice_btn, voice_upload, voice_state],
        )

    return demo


if __name__ == "__main__":
    app = build_app()
    app.queue(default_concurrency_limit=8)
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        show_error=True,
        theme=gr.themes.Soft(
            primary_hue="violet",
            secondary_hue="indigo",
            neutral_hue="slate",
            font=gr.themes.GoogleFont("Inter"),
        ),
        css=CUSTOM_CSS + "footer {display: none !important;} ",
        js=THEME_JS,
    )
