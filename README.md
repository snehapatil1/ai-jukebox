# AI Jukebox 🎵

Generate original songs with matching cover art, and let an AI DJ add spoken
commentary between tracks. A Gradio app powered entirely by the class AI
services (no paid services, no port 9000).

## Status

All four features are implemented and were verified against the live class
services: song generation, cover art (with placeholder + retry), AI DJ
(prefetched, cached, skippable), and the queue player (auto-advancing
song → DJ clip → song, skip, persistence across restarts). See `PROGRESS.md`
for the full step log and test evidence.

## Features

1. **Custom song generation** — pick a style, mood, duration (10–120 s slider,
   enforced 10–120 s in code), instrumental or vocal, and an optional theme.
   Qwen writes the title (and original lyrics for vocal tracks, shown in the
   UI), ACE-Step composes the audio, and the song lands in the library
   immediately with live stage updates and elapsed time.
2. **Matching cover art** — Qwen writes a FLUX-safe prompt (no text, logos,
   real people, or copyrighted characters) and FLUX.2 klein 4B generates the
   cover, stored with the song in the library, queue, and now-playing view.
   If cover generation fails, a placeholder is shown and **Retry cover**
   regenerates only the artwork.
3. **AI DJ** — between queued songs, Qwen writes 2–3 sentences of commentary
   that names both songs (title, style, mood, lyric theme), and Chatterbox
   speaks it. Clips are **prefetched while the current song plays** and cached
   per song pair for the session. If commentary fails or times out, the queue
   skips it with a non-blocking notice. An optional MP3/WAV reference enables
   voice cloning (type + size validated, stored only in the gitignored
   `data/voice_refs/` temp dir, removable/reset from the UI).
4. **Player & queue** — a single `gr.Audio` plays songs and DJ clips
   sequentially (song → DJ clip → song → …) via a state machine in `gr.State`,
   advanced on the audio component's end event. Play/pause on the player,
   **Skip** (works during both a song and DJ speech), a visible queue with a
   now-playing indicator, "add to queue" for any library song, and **Play all**.
   The library persists across server restarts (`data/library.json`).

## Requirements

- Python **3.14.6** (tested)
- macOS system dependency: **ffmpeg** (Gradio probes audio with `ffprobe`)
  ```bash
  brew install ffmpeg
  ```

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then set LLM_API_KEY to your class key
python app.py             # -> http://127.0.0.1:7860
```

### Windows launch and port conflicts

Double-click `launch.bat`. It opens an already-running AI Jukebox instead of starting a duplicate. If no instance is running, it starts the app, waits until it is ready, and opens **http://127.0.0.1:7860** automatically. Keep the server console open; use **Ctrl+C** there when you want to stop it. An unrecognized service on the port is left untouched.

`app.py` explicitly passes `server_name="127.0.0.1"` and `server_port=7860` to `app.launch()`. Setting `GRADIO_SERVER_PORT` alone does not override the explicit argument. If another application needs 7860, identify that process first; do not kill an unknown listener. Choose an available local port in `app.launch()` and update the URL in `launch.bat` accordingly. The local UI port is separate from the class service endpoints—do not change those to fix a local port conflict.

Configuration comes from environment variables or the gitignored `.env`.
The app fails fast at startup if `LLM_API_KEY` is missing. Base URLs default
to the class endpoints and can be overridden per service (see `.env.example`).

## Sample songs

`samples/` holds ready-to-play songs that ship with the repository (they
must appear in the submission ZIP, unlike generated songs in the gitignored
`data/`):

```
samples/
  audio/         sample MP3s
  covers/        sample cover PNGs
  samples.json   manifest: id, title, style, mood, duration_sec,
                 instrumental, theme, lyrics, created_by, cover_prompt,
                 and the audio/cover filenames
```

At startup the app registers every sample in `samples.json` that is not
already in the library — matched by its fixed id, pointing at the files in
place. Nothing is copied into `data/`, and restarting never duplicates a
sample. Samples whose audio or cover file is missing are skipped with a
logged warning, and deleting a sample from the Library tab removes only the
library entry, never the files in `samples/`.

To turn a locally generated song into a sample:

```bash
python scripts/add_sample.py "<song id or title>"
```

The script looks the song up in `data/library.json` (id, exact title, or a
unique title match), copies its MP3 and cover into `samples/`, and appends
its metadata to `samples.json`. Only the song's own audio and cover are
copied — voice references, DJ clips, and everything else in `data/` are
never touched. Re-running it for the same song replaces the existing entry
in place. Commit `samples/` afterwards so the sample ships in the ZIP.

## How the sample songs were made

Each sample was generated through the app itself — the Create tab ran the
same pipeline any user song runs, using only the class AI services: **Qwen
(port 9001)** wrote the title and lyrics, **ACE-Step (port 9007)** composed
the audio, and **FLUX (port 9006)** produced the cover art.

### Sample 1 — "Calloused Fingers Break The Silence" (id `b206632d8cc0`)

- **Genre (custom text):** "epic hard rock, huge distorted guitar riffs,
  thundering live drums, driving bassline, powerful raw male vocals,
  anthemic build"
- **Mood:** Epic — **vocal** — **duration:** 100 s
- **Theme (as entered in the Create tab):**

> genre: epic hard rock, huge distorted guitar riffs, thundering live
> drums, driving bassline, powerful raw male vocals, anthemic build.
> theme: Keeping music human. A singer's voice cracking on the high note
> because she means it; a kid practicing the same chords every night for
> years; a crowd screaming the chorus back. Real people, real voices, real
> passion. Is losing that really progress? Starts heavy and doubtful, ends
> huge and defiant. Never mention algorithms, computers, AI, or machines.

- **Selection process:** about 20 generations were run for this track; the
  best-sounding take was kept. The AI-generated title was kept as is.
- **Cover:** regenerated afterwards in the Cover Art Studio — **Abstract**
  style, description *"Abstract art showing the feeling of loss and
  confusion but still unsettled and defiant."*, palette *"contrast between
  dark blues and orangey reds"*. The final FLUX prompt is stored in
  `samples.json` (`cover_prompt`).
- **Assets:** `samples/audio/b206632d8cc0.mp3`, `samples/covers/b206632d8cc0.png`

### Samples 2 and 3 — pending

Two more sample songs are planned to reach the required three; each will get
the same block here when added.

## Class services used

| Port | Service | Job in this app |
| --- | --- | --- |
| 9001 | Qwen3.6-35B-A3B (`cyankiwi/...-AWQ-4bit`) | titles, lyrics, cover prompts, DJ commentary |
| 9006 | FLUX.2 klein 4B (`black-forest-labs/...`) | cover art |
| 9007 | ACE-Step 1.5 XL Turbo | music generation |
| 9008 | Chatterbox Multilingual V3 | DJ speech (default voice / voice cloning) |

All request formats were verified against the live services (see `PROGRESS.md`).

## Project layout

```
app.py                  # Gradio UI + player state machine (one-command launch)
jukebox/
  config.py             # env config, paths, fail-fast startup checks
  clients.py            # HTTP clients for the four class services
  prompts.py            # prompt contracts (all-original content rules)
  service.py            # pipelines: draft, compose, cover, DJ, voice validation
  library.py            # song library with JSON persistence
  samples.py            # bundled sample loading from samples/ (tracked in git)
samples/                # ready-to-play sample songs (audio/, covers/, samples.json)
scripts/add_sample.py   # turn a generated song into a bundled sample
scripts/smoke_test.py   # end-to-end sanity checks against the live services
```

## Verification

`scripts/smoke_test.py` exercises every feature path against the live class
services (see `PROGRESS.md` for the results and for the two Gradio-6-specific
findings: `theme`/`css` go to `launch()` not `Blocks()`, and the audio end
event is exposed as the `stop` event).

## Limitations

- **Short vocal songs are not fully sung.** The music engine can only sing
  what fits the requested duration: a 10-second vocal track gets roughly a
  verse's worth of singing and the rest plays instrumentally — lyrics are
  shown in full but only a short prefix is sung. Longer tracks (30 s+) sing
  most or all of the text, and the engine may still drop an occasional line
  or section; instrumental tracks are unaffected.

