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
        return "<p style='color:#888'><i>Queue is empty — generate a song or press \"Play all\".</i></p>"
    rows = []
    for i, sid in enumerate(queue):
        song = LIBRARY.get(sid)
        if song is None:
            continue
        is_current = i == pos and mode in ("song", "dj")
        icon = "🎵" if is_current and mode == "song" else ("🎙️" if is_current else "·")
        marker = "▶ " if is_current else ""
        style = (
            "background:#2c2f3a;border:1px solid #6c8cff;"
            if is_current
            else "background:#1d1e26;border:1px solid #333;"
        )
        title = html.escape(song.title)
        credit = ""
        if song.created_by.strip():
            credit = f"<br><span style='color:#7aadd;font-size:12px'>by {html.escape(song.created_by)}</span>"
        meta = f"{html.escape(song.style)} · {html.escape(song.mood)} · "
        meta += "instrumental" if song.instrumental else "vocal"
        rows.append(
            f"<div style='{style} border-radius:8px;padding:6px 10px;margin:4px 0;'"
            f"display:flex;align-items:center;gap:10px;'>"
            f"<img src='{_serve_url(service.cover_display_path(song))}' "
            f"style='width:36px;height:36px;border-radius:6px;object-fit:cover;'>"
            f"<span>{icon}</span><div><b>{marker}{title}</b><br>"
            f"<span style='color:#999;font-size:12px'>{meta}</span>{credit}</div></div>"
        )
    return "<div>" + "".join(rows) + "</div>"


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
def build_app() -> gr.Blocks:
    with gr.Blocks(title="AI Jukebox") as demo:
        gr.Markdown(
            "# 🎵 AI Jukebox\n"
            "Generate original songs with matching cover art, and let an AI DJ "
            "spin commentary between tracks. Powered by the class AI services "
            "on ports 9001 (text), 9006 (cover art), 9007 (music), and 9008 (DJ voice)."
        )
        player_state = gr.State(INITIAL_PLAYER)
        voice_state = gr.State({})

        with gr.Row():
            # ---------------- left column: create + library ----------------
            with gr.Column(scale=2):
                with gr.Tab("✨ Generate a song"):
                    created_by = gr.Textbox("", label="Your name", placeholder="Enter your name for credit")
                    style = gr.Dropdown(GENRES, value="Pop", allow_custom_value=True,
                                        label="Style / genre")
                    mood = gr.Dropdown(MOODS, value="Happy", label="Mood")
                    duration = gr.Slider(config.DURATION_MIN, 60, value=config.DURATION_DEFAULT,
                                         step=5, label="Duration (seconds)")
                    instrumental = gr.Checkbox(False, label="Instrumental (no lyrics)")
                    theme = gr.Textbox("", label="Theme (optional)",
                                       placeholder="e.g. a robot band playing on the moon")
                    gen_btn = gr.Button("🎵 Generate song", variant="primary")
                    gen_status = gr.Markdown("")
                    gen_result = gr.Markdown("")

                with gr.Tab("📚 Library"):
                    _items, _choices = _library_views()
                    library_gallery = gr.Gallery(value=_items, label="Your songs",
                                                 columns=4, height=300, object_fit="cover")
                    song_pick = gr.Dropdown(_choices, label="Song")
                    cover_desc = gr.Textbox(
                        "", lines=4, max_lines=8,
                        label="Cover art description (edit then click Retry cover)",
                        info="Change this text to guide the cover-art prompt, then press 'Retry cover'.",
                    )
                    with gr.Row():
                        add_queue_btn = gr.Button("➕ Add to queue")
                        retry_cover_btn = gr.Button("🖼️ Retry cover")
                        play_all_btn = gr.Button("▶️ Play all")
                    lib_status = gr.Markdown("")

            # ---------------- right column: player + DJ voice ----------------
            with gr.Column(scale=3):
                gr.Markdown("### 🎧 Player")
                now_cover = gr.Image(label="Cover", height=240, interactive=False)
                now_status = gr.Markdown("Nothing playing yet — generate a song or press **Play all**.")
                now_audio = gr.Audio(label="Player", type="filepath", interactive=False,
                                     autoplay=True)
                with gr.Row():
                    play_btn = gr.Button("▶️ Play")
                    skip_btn = gr.Button("⏭️ Skip", interactive=False)
                queue_html = gr.HTML(_queue_html(INITIAL_PLAYER))

                gr.Markdown("### 🎙️ DJ voice")
                voice_upload = gr.Audio(type="filepath", label="Custom DJ voice (optional MP3/WAV)",
                                        sources=["upload"])
                voice_status = gr.Markdown("Using the default bundled DJ voice.")
                remove_voice_btn = gr.Button("🗑️ Remove custom voice", interactive=False)

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
        theme=gr.themes.Soft(),
        css="footer {display: none !important;}",
    )
