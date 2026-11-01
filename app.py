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
import json
import logging
import os
import shutil
import tempfile
import time
import threading
from pathlib import Path
from urllib.parse import quote, unquote

import gradio as gr

from jukebox import clients, config, service
from jukebox.library import Song, SongLibrary

config.setup_logging()
config.check_config()

# --- Load external JS bundle once at import time so it's available everywhere ---
_JUKEBOX_JS = (Path(__file__).parent / "jukebox" / "theme_js.js").read_text(encoding="utf-8")

LOG = logging.getLogger("jukebox.app")
log = LOG  # Preserve legacy pipeline logging calls.

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
    """Serve a repo file through Gradio's file route (origin-relative URL).

    A raw local path (e.g. /Users/.../data/covers/x.png) inside gr.HTML is
    resolved by the browser against the page origin and 404s — the broken
    queue thumbnails came from exactly that. data/covers is registered in
    launch(allowed_paths=...) so this URL works from any working directory.
    """
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
    """Return gallery items and dropdown choices."""
    songs = LIBRARY.all()
    items = [
        (str(service.cover_display_path(s)), f"{s.title} · {s.style} · {s.mood}")
        for s in songs
    ]
    choices = [(s.display_label(), s.id) for s in songs]
    return items, choices


def _cover_for_song(song) -> str:
    """Return a Gradio-safe cover path for a song."""
    return str(service.cover_display_path(song))


def _library_list_html(filter_text: str = "") -> str:
    """Render the compact song-list panel for gr.HTML.

    Each row shows a small square cover, title (wrapping), genre tag, and mood.
    *filter_text* is applied client-side by JS; this function always emits the
    full set so that filtering works without a server round-trip.
    """
    songs = LIBRARY.all()
    if not songs:
        return ('<div id="songListContainer" class="aj-song-list-wrap">'
                '<div class="aj-empty-msg">Library is empty.</div></div>')

    rows = []
    for s in songs:
        cover_url = _serve_url(service.cover_display_path(s))
        title_esc = html.escape(s.title)
        genre_esc = html.escape(s.style)
        mood_esc = html.escape(s.mood)
        # data-id holds the JSON-encoded song record for JS side-clicks; includes cover URL so the panel can update without a round-trip
        row_json = json.dumps({
            "id": s.id, "title": s.title, "style": s.style, "mood": s.mood,
            "cover_url": cover_url
        }, ensure_ascii=False)
        encoded_id = quote(row_json, safe='')
        rows.append(
            f'<div class="aj-song-item" data-id="{encoded_id}">'
            f'<img class="aj-song-cover" src="{cover_url}" alt="" loading="lazy"/>'
            f'<div class="aj-song-info wrap">'
            f'<div class="aj-song-title">{title_esc}</div>'
            f'<div class="aj-song-tags">'
            f'<span class="aj-genre-tag">{genre_esc}</span>'
            f'<span class="aj-mood-tag">{mood_esc}</span>'
            f'</div></div></div>'
        )
    return '<div id="songListContainer" class="aj-song-list-wrap">\n' + "\n".join(rows) + '\n</div>'


def _queue_html(state: dict) -> str:
    queue, pos, mode = state["queue"], state["pos"], state["mode"]
    if not queue:
        return "<p class='aj-queue-empty' style='text-align:center; padding:20px;'><i>🎵 Queue is empty — generate a song or press Play all.</i></p>"
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
            credit = f'<span style="color:var(--aj-muted);font-size:11px;display:block;margin-top:2px">by {html.escape(song.created_by)}</span>'
        meta = f'{html.escape(song.style)} · {html.escape(song.mood)} · {"instrumental" if song.instrumental else "vocal"}'
        cover_url = _serve_url(service.cover_display_path(song))
        rows.append(
            f"<div class='aj-queue-item' style='"
            f"border-radius:10px;padding:8px 12px;margin:6px 0;flex-shrink:0;'>"
            f"<div style='display:flex;align-items:center;gap:12px;'> "
            f"<img src='{cover_url}' style='width:44px;height:44px;border-radius:8px;object-fit:cover;'/>"
            f"<div><b style='color:#e2e8f0'>{icon} {marker}{title}</b>{credit}"
            f"<span style='color:#64748b;font-size:11px;display:block;margin-top:2px'>{meta}</span></div></div></div>"
        )
    return "<div style='display:flex;flex-direction:column;gap:4px;'>\n" + "\n".join(rows) + "\n</div>"


def _lyrics_section(lyrics: str) -> str:
    """Collapsible lyrics panel for the player, styled with the app's theme
    variables (light/dark aware). Shared by _start_song and select_for_player
    so the two can't drift apart (select_for_player used to hardcode dark
    colors, leaving a dark box in light mode)."""
    text = (lyrics or "").strip()
    if not text:
        return ""
    escaped = html.escape(text)
    return (
        '<details style="margin-top:8px">'
        '<summary style="cursor:pointer;font-size:12px;color:var(--aj-accent);font-weight:600">Lyrics</summary>'
        '<p style="color:var(--aj-text);font-size:12px;white-space:pre-line;margin:6px 0 0;'
        'padding:8px;background:var(--aj-input);border-radius:8px;line-height:1.5">'
        f"{escaped}</p></details>"
    )


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
# Gradio's own temp root (the file route's created_paths): per-event audio
# copies placed here are ALWAYS servable, unlike data/ or generic temp dirs.
_GRADIO_TMP = Path(tempfile.gettempdir()) / "gradio"


def _player_state(player_state) -> dict:
    """Normalise the gr.State value into a queue-state dict.

    Older wiring once left a non-dict value (a lyrics HTML string) in the
    state slot when a handler returned more values than its outputs list
    declared; every later state-machine event then crashed with a ValueError
    and the player froze. A non-dict state self-heals to a clean queue here.
    """
    return dict(player_state) if isinstance(player_state, dict) else dict(INITIAL_PLAYER)


def _audio_value(path: Path, autoplay: bool):
    """Audio value the frontend can always load, from a URL that differs on
    every event.

    A raw data path may hit Gradio's file route as unregistered (403 "File
    not allowed"), and bytes values are cached by content hash — same song,
    same URL — which the frontend treats as unchanged, so the playhead is
    never reset. A per-event copy under Gradio's own temp root (the route's
    created_paths) is always served AND has a unique URL, so every load
    reloads the media and starts from 0:00.
    """
    if not path.is_file():
        return gr.update(value=None)
    _GRADIO_TMP.mkdir(exist_ok=True, parents=True)
    src = _GRADIO_TMP / f"aj-player-{time.time_ns()}.mp3"
    shutil.copy2(path, src)
    # Prune by the COPY's creation time (the ns in its name), never by file
    # mtime: copy2 preserves the song's mtime, so mtime-sorted pruning would
    # delete the copies of OLDER songs first — exactly the 403 the user saw
    # ("grey player" for older library songs).
    for old in sorted(
        _GRADIO_TMP.glob("aj-player-*.mp3"),
        key=lambda p: int(p.stem.rsplit("-", 1)[-1]),
    )[:-12]:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass
    return gr.update(value=str(src), autoplay=autoplay)


def _start_song(state: dict, idx: int, voice_state: dict) -> tuple:
    state["pos"], state["mode"] = idx, "song"
    song = LIBRARY.get(state["queue"][idx])
    if song is None:
        state["mode"] = "idle"
        return _queue_html(state), "That song is no longer in the library.", gr.update(), gr.update(value=None), gr.update(interactive=False), '', state
    _spawn_prefetch(state, song, voice_state)
    lyrics_section = _lyrics_section(song.lyrics)
    status = f'**Now playing:** {html.escape(song.title)} — {html.escape(song.style)} · {html.escape(song.mood)}{lyrics_section}'
    credit = f" · by {html.escape(song.created_by)}" if song.created_by.strip() else ""
    status_line = f'### {html.escape(song.title)}\n\n{credit.lstrip(" ·") if credit else ""}\n\n{html.escape(song.style)} · {html.escape(song.mood)} · Now playing'
    return (
        _queue_html(state),
        status_line,
        gr.update(value=str(service.cover_display_path(song))),
        _audio_value(song.abs_audio, True),
        gr.update(interactive=True),
        lyrics_section,
        state,
    )


def advance(player_state: dict, voice_state: dict) -> tuple:
    """Called by the player's `end` event and by Skip.

    song -> DJ clip -> next song -> ... ; state machine lives in gr.State.
    """
    state = _player_state(player_state)
    if state["mode"] == "idle":
        return _queue_html(state), "Nothing is playing.", gr.update(), gr.update(), gr.update(interactive=False), '', state

    if state["mode"] == "song":
        nxt_i = state["pos"] + 1
        if nxt_i >= len(state["queue"]):
            state["mode"] = "idle"
            # Keep the last song loaded (paused at 0:00) instead of removing
            # the audio: the user can replay it without the track vanishing.
            last = LIBRARY.get(state["queue"][state["pos"]])
            last_audio = _audio_value(last.abs_audio, False) if last else gr.update(value=None)
            return (
                _queue_html(state),
                "🏁 Queue finished — thanks for listening!",
                gr.update(), last_audio, gr.update(interactive=False), '', state,
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
                gr.update(), _audio_value(clip, True), gr.update(interactive=True), '', state,
            )
        gr.Info("DJ commentary is unavailable right now — skipping to the next song.")
        return _start_song(state, nxt_i, voice_state)

    # mode == "dj": clip finished -> next song
    nxt_i = state["pos"] + 1
    if nxt_i >= len(state["queue"]):
        state["mode"] = "idle"
        last = LIBRARY.get(state["queue"][state["pos"]])
        last_audio = _audio_value(last.abs_audio, False) if last else gr.update(value=None)
        return (
            _queue_html(state),
            "🏁 Queue finished — thanks for listening!",
            gr.update(), last_audio, gr.update(interactive=False), '', state,
        )
    return _start_song(state, nxt_i, voice_state)


def skip(player_state: dict, voice_state: dict) -> tuple:
    return advance(player_state, voice_state)


def select_for_player(song_id: str | None, player_state: dict) -> tuple:
    """Load a selection without autoplay; keep the player's queue in sync."""
    song = LIBRARY.get(song_id) if song_id else None
    if song is None:
        return (gr.update(),) * 7
    state = _player_state(player_state)
    state["queue"] = [sid for sid in state["queue"] if LIBRARY.get(sid) is not None]
    if song_id not in state["queue"]:
        state["queue"].append(song_id)
    state["pos"] = state["queue"].index(song_id)
    state["mode"] = "song"
    credit = f" · by {html.escape(song.created_by)}" if song.created_by.strip() else ""
    if not song.abs_audio.is_file():
        return (_queue_html(state), f'Audio file is missing for "{html.escape(song.title)}".',
                gr.update(value=str(service.cover_display_path(song))),
                gr.update(value=None), gr.update(interactive=False), '', state)
    lyrics_section = _lyrics_section(song.lyrics)
    status_md = f'### {html.escape(song.title)}\n\n{credit.lstrip(" ·") if credit else ""}\n\n{html.escape(song.style)} · {html.escape(song.mood)} · Ready to play'
    return (_queue_html(state),
            status_md,
            gr.update(value=str(service.cover_display_path(song))),
            _audio_value(song.abs_audio, False),
            gr.update(interactive=True), lyrics_section, state)


def play(player_state: dict, voice_state: dict) -> tuple:
    state = _player_state(player_state)
    if state["mode"] != "idle":
        state["mode"], state["pos"] = "song", max(0, state["pos"])
    elif not state["queue"]:
        state["queue"] = [s.id for s in LIBRARY.all()]
        state["pos"] = 0
    if not state["queue"]:
        return (
            _queue_html(state),
            "The library is empty — generate a song first.",
            gr.update(), gr.update(), gr.update(interactive=False), '', state,
        )
    return _start_song(state, state["pos"], voice_state)


def play_all(player_state: dict, voice_state: dict) -> tuple:
    songs = [s.id for s in LIBRARY.all()]
    if not songs:
        return (
            _queue_html(dict(player_state)),
            "The library is empty — generate a song first.",
            gr.update(), gr.update(), gr.update(interactive=False), '', dict(player_state),
        )
    state = {"queue": songs, "pos": 0, "mode": "idle"}
    return play(state, voice_state)


def add_to_queue(song_id: str, player_state: dict) -> tuple:
    state = _player_state(player_state)
    if not song_id:
        return _queue_html(state), "Select a song in the Library tab first.", state
    song = LIBRARY.get(song_id)
    if song is None:
        return _queue_html(state), "That song no longer exists.", state
    state["queue"].append(song_id)
    return _queue_html(state), f"➕ Added “{song.title}” to the queue.", state


# ---------------------------------------------------------------------------
# generation pipeline
# ---------------------------------------------------------------------------
def _status_html(main: str, started: float, hint: str | None = None, done: bool = False) -> str:
    """Status box: indeterminate animated working bar + stage text + live timer.

    ``done=True`` renders the terminal state (no bar, no timer) used for both
    success and failure.
    """
    if done:
        return f"<div class='aj-status'><div class='aj-status-main'>{main}</div></div>"
    bar = "<div class='aj-progress'><div class='aj-progress-bar'></div></div>"
    time_html = f"<span class='aj-status-time'>{_elapsed(started)}</span>"
    hint_html = f"<div class='aj-status-hint'>{hint}</div>" if hint else ""
    return (
        f"<div class='aj-status'>{bar}"
        f"<div class='aj-status-main'><span class='aj-status-text'>{main}</span>{time_html}</div>"
        f"{hint_html}</div>"
    )


def _friendly_error(exc: Exception) -> str:
    """User-safe error text — no service names, endpoints, ports, or credentials."""
    from jukebox.clients import ServiceError

    if isinstance(exc, service.PipelineError):
        return str(exc)
    if isinstance(exc, ServiceError):
        return "A service couldn't be reached — please try again."
    if isinstance(exc, TimeoutError):
        return "The request timed out — please try again."
    return "Something went wrong — please try again."


def _run_status(fn, main: str, started: float, hint: str | None = None):
    """Run a blocking pipeline stage while yielding a ticking status line.

    The music/lyrics/image services are synchronous, so the stage runs on a
    worker thread and the generator yields one status update per second —
    that is what makes the elapsed timer count up live. Exceptions from the
    worker are re-raised here so the caller's error path handles them.
    """
    holder: dict = {}

    def worker() -> None:
        try:
            holder["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - forwarded to the caller
            holder["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    noop_gallery, noop_pick = gr.update(), gr.update()
    while thread.is_alive():
        yield (gr.update(interactive=False),
               _status_html(main, started, hint),
               "", noop_gallery, noop_pick)
        time.sleep(1)
    thread.join()
    if "error" in holder:
        raise holder["error"]
    return holder["value"]


def generate_song(created_by: str, style: str, mood: str, duration: float, instrumental: bool, theme: str):
    started = time.monotonic()
    noop_gallery, noop_pick = gr.update(), gr.update()

    if instrumental:
        yield (gr.update(interactive=False),
               _status_html("Generating music…", started, "This can take a minute or two."),
               "", noop_gallery, noop_pick)
    else:
        yield (gr.update(interactive=False),
               _status_html("Writing lyrics…", started),
               "", noop_gallery, noop_pick)

    try:
        duration = max(config.DURATION_MIN, min(float(duration), config.DURATION_MAX))

        draft = yield from _run_status(
            lambda: service.write_song_draft(
                style, mood, duration, instrumental, theme,
                existing_titles=tuple(s.title for s in LIBRARY.all())),
            "Writing lyrics…" if not instrumental else "Generating music…",
            started,
            None if not instrumental else "This can take a minute or two.",
        )

        audio_path, meta = yield from _run_status(
            lambda: service.compose_music(style, mood, theme or "", duration, draft["lyrics"]),
            f"Generating “{draft['title']}”…",
            started,
            "This can take a minute or two.",
        )

        cover_rel = ""
        cover_prmpt = ""
        try:
            tmp = Song(
                id="", title=draft["title"], style=style, mood=mood,
                duration_sec=duration, instrumental=instrumental,
                theme=(theme or "").strip(), lyrics=draft["lyrics"],
            )
            cover_abs, cover_prmpt = yield from _run_status(
                lambda: service.generate_cover(tmp),
                "Creating cover art…", started,
            )
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
               _status_html("✅ Added to library", started, done=True),
               result,
               gr.update(value=items), gr.update(choices=choices, value=song.id))
    except GeneratorExit:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any pipeline failure in the UI
        log.exception("Song generation failed")
        yield (gr.update(interactive=True),
               _status_html(f"❌ {_friendly_error(exc)}", started, done=True),
               "", noop_gallery, noop_pick)


def prepare_cover_brief(song_id, description, artistic_style, palette):
    """Ask Qwen for an inspectable brief; never mutate the saved song."""
    song = LIBRARY.get(song_id) if song_id else None
    if song is None:
        return "", None, "Select an existing track first.", None, None
    try:
        prompt = service.cover_prompt_for(
            song, user_description=description or "",
            artistic_style=artistic_style, color_palette=palette or "",
        )
        return prompt, song.id, "Prompt ready — edit it below, then generate a preview.", None, None
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Cover brief preparation failed")
        return gr.update(), None, f"❌ {_friendly_error(exc)} Current cover unchanged.", None, None


def generate_cover_candidate(song_id, prepared_song_id, final_prompt):
    """Render the edited final prompt verbatim, without accepting the result."""
    song = LIBRARY.get(song_id) if song_id else None
    if song is None or song_id != prepared_song_id:
        return None, None, "Select a track and prepare its visual brief first (selection changed)."
    if not final_prompt or not final_prompt.strip():
        return None, None, "Enter a final prompt before generating. Current cover unchanged."
    try:
        cover_abs, _ = service.generate_cover(song, custom_prompt=final_prompt)
        candidate = {"song_id": song.id, "path": str(cover_abs), "prompt": final_prompt}
        return str(cover_abs), candidate, f'New cover ready for “{html.escape(song.title)}” — accept it or keep the current cover.'
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Cover candidate generation failed")
        return None, None, f"❌ {_friendly_error(exc)} Current cover unchanged."


def render_cover_candidate(song_id, prepared_song_id, final_prompt):
    """Publish a visible working state before the blocking image request."""
    yield None, None, "Generating new cover… Current cover is unchanged."
    yield generate_cover_candidate(song_id, prepared_song_id, final_prompt)


def select_cover_track(song_id):
    """Reset drafts and candidates whenever the native track selection changes."""
    song = LIBRARY.get(song_id) if song_id else None
    if song is None:
        return "", None, None, "", None, None, "Select an existing track for cover art."
    return (song.theme or song.cover_prompt or "", _cover_for_song(song), None,
            "", None, None, "Current cover unchanged.")


def accept_cover_candidate(song_id, candidate):
    """The only Studio operation that writes cover fields to the library."""
    song = LIBRARY.get(song_id) if song_id else None
    if song is None or not candidate or candidate.get("song_id") != song_id:
        return (gr.update(), None, None,
                "No matching candidate for this selection. Generate a new cover for the selected track.", gr.update())
    try:
        relative_path = str(Path(candidate["path"]).relative_to(config.ROOT))
        updated = LIBRARY.update(song_id, cover_path=relative_path, cover_prompt=candidate["prompt"])
        if updated is None:
            return gr.update(), None, None, "Track no longer exists. Current cover unchanged.", gr.update()
        return (_cover_for_song(updated), None, None,
                f'New cover accepted for “{html.escape(updated.title)}”.', _library_list_html())
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Accepting cover failed")
        return gr.update(), gr.update(), candidate, f"❌ {_friendly_error(exc)}", gr.update()


def keep_current_cover():
    return None, None, "Current cover kept. New candidate discarded."


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
def delete_song(song_id: str | None, player_state: dict):
    # Missing/stale selection must never empty the visible library.
    state = _player_state(player_state)

    def response(message, selection=None):
        items, choices = _library_views()
        return (message, gr.update(choices=choices, value=selection),
                gr.update(value=items, selected_index=None), _queue_html(state))

    if not song_id:
        return response("Select a song before deleting.")
    song = LIBRARY.get(song_id)
    if song is None:
        return response("That song is no longer in the library. The list has been refreshed.")
    if not LIBRARY.delete(song_id):
        return response(f'Could not delete "{html.escape(song.title)}". Please try again.', song_id)

    if song_id in state.get("queue", []):
        old_queue = state["queue"]
        old_pos = state["pos"]
        current_id = old_queue[old_pos] if 0 <= old_pos < len(old_queue) else None
        state["queue"] = [sid for sid in old_queue if sid != song_id]
        if current_id in state["queue"]:
            state["pos"] = state["queue"].index(current_id)
        else:
            state["pos"] = 0
            state["mode"] = "idle"
    return response(f'Deleted "{html.escape(song.title)}".')


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
from jukebox.theme import CUSTOM_CSS, THEME_JS, DOM_WRAP_JS

def filter_library(query: str = ""):
    """Native gallery values and exact stable IDs for the filtered list."""
    query = (query or "").casefold().strip()
    songs = [s for s in LIBRARY.all() if not query or query in
             f"{s.title} {s.style} {s.mood}".casefold()]
    return ([(str(service.cover_display_path(s)), f"{s.title}\n{s.style} · {s.mood}") for s in songs],
            [s.id for s in songs])


def refresh_filtered_library(query: str = ""):
    """Refresh visible tracks and clear selection without changing playback."""
    items, ids = filter_library(query)
    return gr.update(value=items, selected_index=None), ids, None


def initialize_session():
    """Read the live library on each browser load, not when Blocks is built."""
    items, ids = filter_library()
    first_id = ids[0] if ids else None
    choices = [(s.display_label(), s.id) for s in LIBRARY.all()]
    state = {"queue": [], "pos": 0, "mode": "idle"}
    player = select_for_player(first_id, state) if first_id else (
        _queue_html(state), "Select a song from your library.",
        gr.update(value=None), gr.update(value=None),
        gr.update(interactive=False), "", state,
    )
    return (gr.update(value=items, selected_index=0 if ids else None), ids,
            gr.update(choices=choices, value=first_id), first_id,
            *player, *select_cover_track(first_id))


def build_app() -> gr.Blocks:
    items, song_ids = filter_library()
    first_id = song_ids[0] if song_ids else None
    with gr.Blocks(title="AI Jukebox") as demo:
        gr.HTML('''<header class="aj-header"><div class="aj-brand"><svg class="aj-logo" viewBox="0 0 64 64" fill="none" aria-hidden="true" focusable="false"><defs><linearGradient id="ajVinylGradient" x1="10" y1="7" x2="54" y2="59" gradientUnits="userSpaceOnUse"><stop stop-color="#c4a5ff"/><stop offset=".5" stop-color="#8955ff"/><stop offset="1" stop-color="#4ed7ed"/></linearGradient></defs><path d="M32 5C17.1 5 5 17.1 5 32s12.1 27 27 27 27-12.1 27-27S46.9 5 32 5Z" fill="url(#ajVinylGradient)" opacity=".12"/><circle cx="32" cy="32" r="22" fill="#10172f" stroke="url(#ajVinylGradient)" stroke-width="3"/><path d="M18 29a14.5 14.5 0 0 1 17-11M46 35a14.5 14.5 0 0 1-17 11" stroke="url(#ajVinylGradient)" stroke-width="2" stroke-linecap="round" opacity=".75"/><circle cx="32" cy="32" r="10" fill="url(#ajVinylGradient)"/><path d="m30 27 7 5-7 5V27Z" fill="white"/><path d="M7 43c-6-1-5-7 2-13M55 21c8-1 10 3 4 9-6 7-18 14-31 18-10 3-19 3-22 0" stroke="url(#ajVinylGradient)" stroke-width="2.5" stroke-linecap="round"/><path d="m49 4 1.4 4.6L55 10l-4.6 1.4L49 16l-1.4-4.6L43 10l4.6-1.4L49 4Z" fill="#d9c8ff"/><circle cx="10" cy="16" r="2" fill="#64d7ed"/></svg><div><h1 id="mainTitle">AI Jukebox</h1><p id="mainDesc">Your music, made by you.</p></div></div><button type="button" id="themeToggle" aria-label="Switch to light theme" title="Switch theme">☀</button></header>''', elem_id="brandHeader")
        player_state = gr.State(INITIAL_PLAYER)
        voice_state = gr.State({})
        selected_song = gr.State(first_id)
        gallery_ids = gr.State(song_ids)
        # Retained compatibility output for the cover acceptance helper.
        song_list_html = gr.HTML(visible=False, elem_id="songListHTML")
        with gr.Tabs(selected="library", elem_id="jukeboxTabs"):
            with gr.Tab("Create", id="create"):
                with gr.Group(elem_id="studioPanel"):
                    gr.Markdown("## Create a song\nChoose a sound and tell your story.")
                    created_by = gr.Textbox("", label="Artist name", placeholder="Your name or band")
                    with gr.Row():
                        style = gr.Dropdown(GENRES, value="Pop", allow_custom_value=True, label="Genre")
                        mood = gr.Dropdown(MOODS, value="Happy", label="Mood")
                    duration = gr.Slider(config.DURATION_MIN, 60, value=config.DURATION_DEFAULT, step=5, label="Duration (seconds)")
                    instrumental = gr.Checkbox(False, label="Instrumental (no lyrics)")
                    theme = gr.Textbox("", label="Theme / Story", lines=3, placeholder="What is your song about?")
                    gen_btn = gr.Button("Generate Song", variant="primary")
                    gen_status = gr.HTML('', elem_id="genStatusBox")
                    gen_result = gr.Markdown('')
                with gr.Accordion("DJ voice settings", open=False):
                    voice_upload = gr.Audio(type="filepath", label="Custom DJ voice", sources=["upload"])
                    voice_status = gr.Markdown("Using default bundled DJ voice.")
                    remove_voice_btn = gr.Button("Remove custom voice", interactive=False, variant="secondary")
            with gr.Tab("Library", id="library"):
                with gr.Row(equal_height=False, elem_id="libraryLayout"):
                    with gr.Column(scale=3, min_width=0, elem_id="libraryPanel"):
                        gr.Markdown("## Your library")
                        lib_search = gr.Textbox("", label="Search your songs", show_label=False,
                                                placeholder="Search your songs…", elem_id="libSearchBox")
                        library_gallery = gr.Gallery(items, columns=1, rows=6, height="auto", buttons=[],
                            allow_preview=False, preview=False, show_label=False,
                            object_fit="cover", selected_index=0 if items else None,
                            elem_id="libraryGallery")
                        with gr.Row():
                            add_queue_btn = gr.Button("Add to queue", size="sm")
                            play_all_btn = gr.Button("Play all", variant="primary", size="sm")
                        with gr.Accordion("Library actions", open=False):
                            refresh_library_btn = gr.Button("Refresh library", size="sm")
                            delete_song_btn = gr.Button("Delete selected song", variant="stop", size="sm")
                        lib_status = gr.Markdown("", elem_classes=["aj-status-hint"])
                    with gr.Column(scale=4, min_width=0, elem_id="playerPanel"):
                        gr.Markdown("## Now playing")
                        with gr.Group(elem_id="nowPlayingPanel"):
                            now_cover = gr.Image(label="Album artwork", show_label=False, height=250,
                                                 interactive=False, buttons=["download"], elem_id="nowCover")
                            now_meta = gr.Markdown("Select a song from your library.", elem_id="nowMeta")
                            now_audio = gr.Audio(label="Playback", show_label=False, type="filepath",
                                interactive=False, autoplay=False, buttons=["download"], elem_id="nowAudio")
                            with gr.Row():
                                skip_btn = gr.Button("Next track", interactive=False, size="sm", elem_id="skipBtn")
                            lyrics_section = gr.HTML('', elem_id="lyricsSection")
                        gr.Markdown("### Up next")
                        queue_html = gr.HTML(_queue_html(INITIAL_PLAYER), elem_id="queuePanel")
                        # Reserved UI space only. DJ controls/parameters belong to the team integration.
                        with gr.Group(elem_id="djOptionsPanel"):
                            gr.Markdown("### DJ options")
                            gr.Markdown("Coming soon.",
                                        elem_classes=["aj-status-hint"])
                    with gr.Column(scale=4, min_width=0, elem_id="coverArtStudio"):
                        gr.Markdown("## Cover art studio\nGive your song a visual identity.")
                        cover_track = gr.Dropdown(choices=[(s.display_label(), s.id) for s in LIBRARY.all()],
                            value=first_id, label="Editing cover for", interactive=True)
                        cover_description = gr.Textbox(label="Describe your cover art", lines=2, max_lines=4, interactive=True)
                        cover_style = gr.Radio(["Photo", "Illustration", "Minimal", "Abstract"],
                            value="Illustration", label="Artistic style", elem_id="coverStyle")
                        cover_palette = gr.Textbox(label="Color palette (optional)", placeholder="e.g. turquoise, warm gold, cream")
                        prepare_cover_btn = gr.Button("Improve my description", variant="secondary", size="sm")
                        with gr.Accordion("Inspect / edit final prompt", open=False, elem_id="finalPromptPanel") as final_prompt_panel:
                            final_cover_prompt = gr.Textbox(label="Final FLUX prompt (editable)", lines=4, interactive=True)
                        prepared_cover_track = gr.State(None)
                        cover_candidate = gr.State(None)
                        generate_cover_btn = gr.Button("Generate new cover", variant="primary")
                        cover_studio_status = gr.Markdown("Your audio stays unchanged.", elem_id="coverStudioStatus")
                        with gr.Row(elem_id="coverPreviews"):
                            with gr.Column(scale=1, min_width=0):
                                gr.Markdown("**Current**", elem_id="currentCoverLabel")
                                current_cover_preview = gr.Image(label="Current", show_label=False, interactive=False,
                                    buttons=[], container=False, height=120, min_width=0, elem_id="currentCoverPreview")
                            with gr.Column(scale=1, min_width=0):
                                gr.Markdown("**New preview**", elem_id="newCoverLabel")
                                new_cover_preview = gr.Image(label="New preview", show_label=False, interactive=False,
                                    buttons=[], container=False, height=120, min_width=0, elem_id="newCoverPreview")
                        with gr.Row(elem_id="coverActions"):
                            accept_cover_btn = gr.Button("Use this cover", variant="primary")
                            keep_cover_btn = gr.Button("Keep current", variant="secondary")
                        gr.Markdown("Improve refines the prompt. Generate creates an image preview. Your audio stays unchanged.", elem_classes=["aj-status-hint"])

        player_outputs = [queue_html, now_meta, now_cover, now_audio, skip_btn, lyrics_section, player_state]
        def choose_song(ids, state, evt: gr.SelectData):
            index = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
            if not evt.selected or not isinstance(index, int) or index < 0 or index >= len(ids):
                return (gr.update(),) * 9
            sid = ids[index]
            return (*select_for_player(sid, state), sid, gr.update(value=sid))
        library_gallery.select(choose_song, inputs=[gallery_ids, player_state],
            outputs=[*player_outputs, selected_song, cover_track])
        lib_search.change(refresh_filtered_library, inputs=[lib_search], outputs=[library_gallery, gallery_ids, selected_song])
        refresh_library_btn.click(refresh_filtered_library, inputs=[lib_search], outputs=[library_gallery, gallery_ids, selected_song])
        add_queue_btn.click(add_to_queue, inputs=[selected_song, player_state], outputs=[queue_html, lib_status, player_state])
        play_all_btn.click(play_all, inputs=[player_state, voice_state], outputs=player_outputs)
        # Play/pause, seeking, speed and volume use the single native Gradio player.
        skip_btn.click(skip, inputs=[player_state, voice_state], outputs=player_outputs)
        now_audio.stop(advance, inputs=[player_state, voice_state], outputs=player_outputs)

        def refresh_cover_choices():
            return gr.update(choices=[(s.display_label(), s.id) for s in LIBRARY.all()])
        cover_track.change(select_cover_track, inputs=[cover_track],
            outputs=[cover_description, current_cover_preview, new_cover_preview,
                     final_cover_prompt, prepared_cover_track, cover_candidate, cover_studio_status])
        demo.load(initialize_session,
            outputs=[library_gallery, gallery_ids, cover_track, selected_song,
                     *player_outputs, cover_description, current_cover_preview,
                     new_cover_preview, final_cover_prompt, prepared_cover_track,
                     cover_candidate, cover_studio_status])
        prepare_cover_btn.click(prepare_cover_brief,
            inputs=[cover_track, cover_description, cover_style, cover_palette],
            outputs=[final_cover_prompt, prepared_cover_track, cover_studio_status, cover_candidate, new_cover_preview]).then(
                lambda: gr.update(open=True), outputs=[final_prompt_panel])
        rendered = generate_cover_btn.click(
            lambda: gr.update(interactive=False), outputs=[keep_cover_btn], queue=False).then(
            render_cover_candidate,
            inputs=[cover_track, prepared_cover_track, final_cover_prompt],
            outputs=[new_cover_preview, cover_candidate, cover_studio_status])
        rendered.then(lambda: gr.update(interactive=True), outputs=[keep_cover_btn], queue=False)
        rendered.then(
            lambda candidate: gr.update(open=not bool(candidate)), inputs=[cover_candidate], outputs=[final_prompt_panel])
        for source in (cover_description, cover_style, cover_palette):
            source.change(lambda: None, outputs=[prepared_cover_track])
        accepted = accept_cover_btn.click(accept_cover_candidate, inputs=[cover_track, cover_candidate],
            outputs=[current_cover_preview, new_cover_preview, cover_candidate, cover_studio_status, song_list_html])
        accepted.then(refresh_filtered_library, inputs=[lib_search], outputs=[library_gallery, gallery_ids, selected_song])
        def refresh_player_art(state):
            queue = state.get("queue", [])
            pos = state.get("pos", 0)
            song = LIBRARY.get(queue[pos]) if 0 <= pos < len(queue) else None
            return gr.update(value=_cover_for_song(song)) if song else gr.update()
        accepted.then(refresh_player_art, inputs=[player_state], outputs=[now_cover])
        keep_cover_btn.click(keep_current_cover, outputs=[new_cover_preview, cover_candidate, cover_studio_status])
        generated = gen_btn.click(generate_song,
            inputs=[created_by, style, mood, duration, instrumental, theme],
            outputs=[gen_btn, gen_status, gen_result, library_gallery, cover_track])
        generated.then(refresh_filtered_library, inputs=[lib_search], outputs=[library_gallery, gallery_ids, selected_song])
        generated.then(refresh_cover_choices, outputs=[cover_track])
        def delete_selected(sid, state):
            message, _, _, _ = delete_song(sid, state)
            state = _player_state(state)
            state["queue"] = [item for item in state["queue"] if LIBRARY.get(item)]
            state["pos"] = min(state["pos"], max(0, len(state["queue"]) - 1))
            if not state["queue"]:
                state["mode"] = "idle"
            return message, sid if LIBRARY.get(sid) else None, _queue_html(state), state
        deleted = delete_song_btn.click(delete_selected, inputs=[selected_song, player_state],
            outputs=[lib_status, selected_song, queue_html, player_state])
        deleted.then(refresh_filtered_library, inputs=[lib_search], outputs=[library_gallery, gallery_ids, selected_song])
        deleted.then(refresh_cover_choices, outputs=[cover_track])
        voice_upload.change(on_voice_upload, inputs=[voice_upload, voice_state],
            outputs=[voice_status, remove_voice_btn, voice_upload, voice_state])
        remove_voice_btn.click(on_voice_remove, inputs=[voice_state],
            outputs=[voice_status, remove_voice_btn, voice_upload, voice_state])
    return demo


if __name__ == "__main__":
    app = build_app()
    app.queue(default_concurrency_limit=8)
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        show_error=True,
        # Cover art lives under data/covers; registering it here lets the
        # /gradio_api/file= URLs used by queue/gallery thumbnails always be
        # served, regardless of the working directory the app was launched from.
        allowed_paths=[str(config.DATA_DIR), str(Path(__file__).parent / "jukebox")],
        theme=gr.themes.Soft(
            primary_hue="violet",
            secondary_hue="indigo",
            neutral_hue="slate",
            font=gr.themes.GoogleFont("Inter"),
        ),
        css=CUSTOM_CSS + "footer {display: none !important;} ",
        # --- Global JS via head (executes before SPA hydration) ---
        head='<style>' + (Path(__file__).parent / 'jukebox' / 'workspace.css').read_text(encoding='utf-8') + '</style><script>' + _JUKEBOX_JS + '</script>',
    )
