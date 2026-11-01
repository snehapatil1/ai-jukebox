# PROGRESS — AI Jukebox (Assignment 3)

Step-by-step log of what was done, probed, and verified. All service formats
were confirmed with REAL live requests before code was written; nothing here
is assumed or fabricated.

## Step 1 — Repo setup
- Cloned `https://github.com/snehapatil1/ai-jukebox.git` into `Assignment3/`.
- Created branch `sneha` from `master` (all further work on `sneha`).
- `gh` authenticated as `snehapatil1`; Python 3.14.6; venv created with
  `gradio==6.30.0`, `python-dotenv==1.2.4`, `requests==2.34.2`, `pillow==12.3.0`.

## Step 2 — Service probing (before any app code)
Formats verified with minimal live requests (see `scripts/smoke_test.py` for
the repeatable checks):

- **9001 Qwen (text)**: OpenAI-compatible `POST /v1/chat/completions`, model
  `cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit`. It is a REASONING model — verified that
  small `max_tokens` (e.g. 160) can be fully consumed by internal reasoning
  (`finish=length`, `content=None`); chains measured up to 8k+ tokens, so
  "empty" replies were reproducible. Fix verified: `chat_template_kwargs:
  {"enable_thinking": False}` → reliable answers in ~0.2–1 s. Creative calls
  (title, lyrics, cover prompt) now sample at `temperature 0.9`
  (`config.CREATIVE_TEMPERATURE`) — 0.0 made same-settings generations
  near-deterministic (identical titles/lyrics). A `max_tokens >= 1024` guard is
  enforced in the client.
- **9006 FLUX**: `POST /v1/images/generations` → `data[0].b64_json` PNG
  (1024×1024). Output visually confirmed (red apple probe).
- **9007 ACE-Step**: async task API per its docs — `POST /release_task`
  (prompt, lyrics, audio_duration, audio_format=mp3, vocal_language) →
  `task_id`; poll `POST /query_result` (status 1 = done, 2 = failed; result is
  a JSON string with `file` paths and `metas`); download `GET /v1/audio?path=...`.
  Each task returned 2 MP3 variants; first successful one is kept. 10 s probe
  generated in ~3–15 s.
- **9008 Chatterbox**: `POST /v1/audio/speech` (model `chatterbox-v3`, `input`,
  `language_id`, optional `ref_audio` base64) → MP3. `GET /v1/voices` shows the
  bundled `default` voice. Server limits from `GET /info`: input ≤ 4096 chars,
  body ≤ 32 MB, reference audio ≤ 20 MB / 60 s — enforced in `validate_voice_file`
  (MP3/WAV only, ≤ 15 MB).

## Step 3 — Build
- `jukebox/` package: `config.py` (env-only config, fail fast), `clients.py`,
  `prompts.py`, `service.py` (draft/compose/cover/DJ pipelines), `library.py`
  (JSON persistence, relative paths only).
- `app.py`: Gradio UI, single `gr.Audio` player, sequential state machine
  (song → DJ clip → song → …) in `gr.State`, advanced on the audio end event;
  DJ clips prefetched in a background thread while the song plays and cached
  per (song pair, voice) for the session; skip works during songs and DJ
  speech; placeholder cover + Retry cover; custom voice upload w/ validation,
  gitignored storage, remove/reset.

### Gradio 6.30 findings (documented for the report)
- `theme`/`css` belong in `launch()`, not `Blocks()` (removed-parameter warning).
- `gr.Audio` has no `show_download_button`, and NO `end` event — the DOM
  `ended` event is wired to the component's **`stop`** event (`onstop`), which
  is what drives queue advancement; `pause` stays user-pause only.
- `gr.Dropdown` with dict `choices` ignores dict values (keys become values) →
  use `(label, value)` tuples.
- **ffprobe dependency**: Gradio's audio post-process requires `ffprobe`
  (part of ffmpeg) to validate audio paths; without it, any player value
  update crashes in `processing_utils.audio_is_playable`. `brew install ffmpeg`
  on the dev machine (documented in README as a system requirement).

## Step 4 — Verification (all run against live services)
- `scripts/smoke_test.py` — 8/8 checks passed:
  1. vocal title+lyrics (Qwen) — passed, ~0.7 s
  2. instrumental title only — passed, ~0.2 s
  3. ACE-Step compose (10 s MP3) — passed, ~9–15 s
  4. cover prompt → FLUX PNG — passed, ~2.6 s
  5. DJ commentary (names both songs) + Chatterbox clip — passed
  6. voice validation (accepts MP3, rejects non-audio) — passed
- **Live player/queue test (real browser + the app's own API)** — full queue
  state machine verified with two 10 s test songs (removed afterwards):
  - Auto-advance: song 1 → DJ clip → song 2 → "Queue finished" with NO clicks
    after the initial Play all (timeline: 10 s song, ~5 s DJ clip, 10 s song).
  - **Autoplay findings** (what was tried): Gradio 6.30 sets the audio value and
    expects the browser to play it. Synthetic `element.click()` calls from
    automation are NOT user gestures, so Chrome's autoplay policy blocked
    playback (audio stayed paused at 0:00). With a genuine user-activation
    click (CDP `Runtime.evaluate userGesture`), everything played — including
    the mid-queue DJ clip and the second song, with zero further input.
    **No workaround was needed**: after the first real Play click the queue
    advances automatically, exactly as the spec asks. (Docs note: in a
    headless/automated browser without real gestures, playback is blocked by
    the browser, not by the app.)
  - Skip: during a song → jumps to the DJ clip; during DJ speech → jumps to
    the next song; during the last song → "Queue finished".
  - DJ commentary verified in the live transcript (names both songs, style,
    mood, content is on-topic).
  - Add to queue (queue grew to 3 rows with ▶ now-playing highlight in the UI).
  - Custom voice: real MP3 accepted + "voice cloning enabled", removal resets
    to default, a .txt file rejected with a clear message; ≤15 MB guard in code.
  - Retry cover: regenerates the PNG without touching the audio.
  - Persistence: server restart → both songs reloaded from `data/library.json`.
- **Bug found & fixed during testing**: the Library tab did not reflect songs
  persisted from a previous run until a new song was generated — gallery and
  song dropdown are now seeded from the library at startup.
- UI smoke run (local `python app.py`, real browser): generated two test songs
  end to end through the Gradio UI (vocal "Moonlight Beat Drop" and
  instrumental "Lunar Beat Drop", ~11 s each incl. FLUX cover: BPM/metadata
  shown, lyrics displayed, both songs in the library with covers rendering).
  Test songs were removed afterwards to leave the library clean.

## Step 5 — Status
- All four core features verified against the live services (see Step 4).
- Remaining: push `sneha` and open/maintain the PR `sneha → master` **on the
  user's go-ahead** (the branch is already pushed; PR #1 was auto-created
  before the user asked to hold off).
- Test songs were removed after every verification run; the library is clean.
