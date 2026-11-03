# AI Jukebox 🎵

Generate original songs with matching cover art, and let an AI DJ add spoken
commentary between tracks. A Gradio app powered entirely by the class AI
services (no paid services, no port 9000).

## Status

Song generation, cover art, and DJ speech have been exercised against the
live class services. Automated tests cover queue transitions and persistence.
See the verification section below for current results and limitations;
earlier development notes are in `PROGRESS.md`.

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
   per song pair for the session.

   **DJ Voice:** By default the bundled Chatterbox voice is used automatically.
   To customize the DJ's voice, upload a short audio recording as a reference.
   Supported formats: MP3 and WAV. If usage fails, the DJ falls back to the default
   voice and displays a notice. The voice reference must be 3–60 seconds long;
   shorter or longer files are rejected. Recorded references are stored only in
   the gitignored `data/voice_refs/` directory and can be removed at any time.
4. **Player & queue** — a single `gr.Audio` plays songs and DJ clips
   sequentially (song → DJ clip → song → …) via a state machine in `gr.State`,
   advanced on the audio component's end event. Play/pause on the player,
   **Skip** (works during both a song and DJ speech), a visible queue with a
   now-playing indicator, "add to queue" for any library song, and **Play all**.
   The library persists across server restarts (`data/library.json`).

## Requirements

- Python **3.10 or newer** (tested on Python 3.14.6 on macOS)
  - macOS's built-in `python3` (version 3.9) is too old for this project.
    Install Python from [python.org](https://www.python.org/downloads/macos/)
    (the macOS Installerpkg works well), then create a virtual environment:

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

- **ffmpeg** is required for audio validation and voice reference conversion
  (Gradio also probes audio with `ffprobe`):
  - **macOS:** `brew install ffmpeg`
  - **Windows:** Download from [ffmpeg.org](https://ffmpeg.org/download.html)
    or use `choco install ffmpeg`, then add to your PATH, or download the
    static build and place `ffmpeg.exe` somewhere on your PATH.

## Quick start

```bash
source .venv/bin/activate    # activate the virtual environment
cp .env.example .env         # then set LLM_API_KEY to your class key
python app.py                # -> http://127.0.0.1:7860
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

### Sample 2 — "Steam Fogs The Glass Pane" (id `9aa2f071d359`)

- Lo-fi / Calm / instrumental; requested 15 seconds.
- Theme: "Rain on a quiet cafe window".
- Qwen generated the title and cover prompt, ACE-Step generated the audio,
  and FLUX generated the rainy-window artwork through the app pipeline.
- The first successful take was retained. This was generated before the
  duration fix and is 14.088 seconds long; the manifest records actual duration.
- Assets: `samples/audio/9aa2f071d359.mp3`, `samples/covers/9aa2f071d359.png`.

### Sample 3 — "Blue Highlighters and Empty Pizza Boxes" (id `85b61f7ac792`)

- Pop / Happy / vocal; requested 35 seconds.
- Theme: "Friends celebrating finishing a difficult class project".
- Qwen generated the title, original lyrics, and cover prompt; ACE-Step
  generated the audio; FLUX generated the artwork of friends celebrating.
- The first successful take was retained. This was generated before the
  duration fix and is 32.376 seconds long; the manifest records actual duration.
- Assets: `samples/audio/85b61f7ac792.mp3`, `samples/covers/85b61f7ac792.png`.

All three sample MP3s and PNGs are included in `samples/`. User uploads and
voice references are not part of the samples. Generation and file decoding
were checked; a human listening review is still needed for vocal quality.

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

### Local verification of the submission fixes (November 2, 2026)

- `python -m unittest discover -s tests -p 'test_*.py'`: **41 passed**.
  The audio duration regression requires ffmpeg and is skipped if unavailable.
- `python scripts/smoke_test.py`: **8 passed, 0 failed** against class
  services after fixing the cover-result unpacking. One earlier attempt was
  interrupted by a text-service disconnection; the next complete run passed.
- New 10-second music request: **10.032 seconds** measured with ffprobe.
  We removed automatic silence trimming to preserve the full service render.
  This retains natural fades and avoids changing tempo or adding artificial padding.
- All three samples have bundled audio and cover files. The two added samples
  were generated before the duration fix; their metadata records measured length.
- Earlier local checks verified default DJ speech, synthetic MP3/WAV reference
  requests, song persistence across a server restart, and correct cover selection.
  A simulated timeout re-enabled generation and showed a retry message;
  2-second/65-second WAV files and unsupported text files were rejected.
- **Still unverified in this review:** audible singing quality, human voice
  likeness, and uninterrupted browser playback without overlapping sound.
  The in-app browser's player did not advance; Chrome automation was unreliable.
  Queue state transitions pass automated tests, but that is not a listening test.

For the final listening check, open the app in a normal browser, press **Play all**,
listen through song → DJ → next song, pause/resume mid-track, and use **Next track**
during DJ speech. Confirm the vocal sample has singing and only one clip is audible.

## Test Results (AI DJ Feature)

Tests performed on macOS with Python 3.14.6, connected to live class services
(ports 9001 and 9008). Script-based validations ran via `jukebox.service` in a
test harness; manual tests were run through the live Gradio app.

| Input | Expected | Actual | Status |
| --- | --- | --- | --- |
| Vocal song, 10 s | Generated track with some singing | Generated, but NO audible singing — instrumental only | Observed |
| Vocal song, 35 s | Generated track with clear singing | Singing audible, sounded right | Verified |
| Play all with 2+ songs, default DJ voice | Song → DJ commentary → next song, automatic | Song → DJ commentary about both songs → next song, automatic; commentary text shown under player | Verified |
| Skip during DJ speech | Jump to next song without overlap | Jumped to next song, no overlapping audio | Verified |
| Custom voice, MP3 (user recording) | DJ uses user's voice clone | DJ sounded like the user | Verified |
| Custom voice, WAV (user recording) | DJ uses user's voice clone | DJ sounded like the user | Verified |
| Custom voice, .m4a (iPhone Voice Memo) | Rejected — not a supported format | File picker allows .m4a, but nothing happens — no file shown, no error. Known issue; use MP3 or WAV. | Known issue |
| Unsupported format (.txt) dragged onto voice box | Clear warning: only MP3 or WAV accepted | Clear warning displayed | Verified |
| Invalid voice reference (~2 s short) | Rejected with "must be 3–60 seconds" message | Rejected, clear error shown | Script verified |
| Invalid voice reference (~65 s long) | Rejected with "must be 3–60 seconds" message | Rejected, clear error shown | Script verified |
| Custom voice engine failure (invalid/non-speech audio) | Fall back to default voice, show gr.Warning | Fallback triggered on any exception, gr.Warning displayed | Verified |
| Custom voice render timeout (>4.5 min wait) | Fall back to default voice, show gr.Info | Same fallback behavior confirmed | Code reviewed |

![DJ commentary](screenshots/dj-commentary.png)

## Limitations

- Music is now saved exactly as returned by ACE-Step, including quiet endings.
  The former silence trimming shortened requested durations; preserving the
  render avoids that change without speeding up or padding the music. Service
  timing and MP3 framing may still introduce small differences.

- **Short vocal songs are not fully sung.** The music engine can only sing
  what fits the requested duration: a 10-second vocal track gets roughly a
  verse's worth of singing and the rest plays instrumentally — lyrics are
  shown in full but only a short prefix is sung. We recommend 30 s or more for
  tracks where you want clear vocals. Longer tracks (30 s+) sing most or all of
  the text, and the engine may still drop an occasional line or section; instrumental tracks are unaffected.
