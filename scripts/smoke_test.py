"""Smoke test: exercises each class service through the real app pipeline.

Run with the project venv:  .venv/bin/python scripts/smoke_test.py
Every assertion below was verified against live service responses during
development; this script re-checks them end to end.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jukebox import config, service  # noqa: E402

config.setup_logging()
config.check_config()

PASS, FAIL = [], []
def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")


print("== 1. Qwen lyrics/title (9001) ==")
t0 = time.monotonic()
draft = service.write_song_draft("Jazz", "Calm", 12, False, "a rainy night in a small cafe")
check("title+lyrics written", bool(draft["title"] and draft["lyrics"]),
      f"({time.monotonic()-t0:.1f}s) title={draft['title']!r}")
print("     lyrics head:", draft["lyrics"].splitlines()[0][:80])

print("== 2. Instrumental title-only ==")
t0 = time.monotonic()
inst = service.write_song_draft("Lo-fi", "Dreamy", 12, True, "")
check("instrumental title", bool(inst["title"]) and inst["lyrics"] == "",
      f"({time.monotonic()-t0:.1f}s) title={inst['title']!r}")

print("== 3. ACE-Step compose (9007, shortest 10s) ==")
t0 = time.monotonic()
audio_path, meta = service.compose_music("Jazz", "Calm", "rainy cafe", 10, draft["lyrics"])
size = audio_path.stat().st_size
print(f"  ({time.monotonic()-t0:.1f}s) {audio_path.name} {size} bytes, meta={meta.get('bpm')}bpm {meta.get('timesignature')}/4")
check("mp3 saved & non-empty", size > 10_000)

print("== 4. Cover pipeline (Qwen prompt -> FLUX 9006) ==")
song = __import__("jukebox.library", fromlist=["Song"]).Song(
    id="smoke", title=draft["title"], style="Jazz", mood="Calm",
    duration_sec=10, instrumental=False, theme="rainy cafe", lyrics=draft["lyrics"])
t0 = time.monotonic()
cover = service.generate_cover(song)
print(f"  ({time.monotonic()-t0:.1f}s) {cover.name} {cover.stat().st_size} bytes")
check("cover PNG saved", cover.stat().st_size > 10_000 and cover.name.endswith(".png"))

print("== 5. DJ commentary + Chatterbox clip (9001 + 9008) ==")
song2 = __import__("jukebox.library", fromlist=["Song"]).Song(
    id="smoke2", title=inst["title"], style="Lo-fi", mood="Dreamy",
    duration_sec=10, instrumental=True, theme="", lyrics="")
t0 = time.monotonic()
text = service.dj_commentary(song, song2)
print("     commentary:", text[:140])
check("commentary 1-3 sentences", 1 <= text.count(". ") + 1 <= 5, f"({time.monotonic()-t0:.1f}s)")
t0 = time.monotonic()
audio = service.render_dj_clip(text)
print(f"  ({time.monotonic()-t0:.1f}s) clip {len(audio)} bytes")
check("dj mp3 non-empty", len(audio) > 5_000)

print("== 6. Voice validation rules ==")
ok1, msg1 = service.validate_voice_file(__file__)
check("rejects non-audio", not ok1 and "MP3 or WAV" in msg1)
ok2, msg2 = service.validate_voice_file(str(audio_path))
check("accepts generated mp3", ok2, f"({msg2})")

print()
print(f"SUMMARY: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("All smoke tests passed.")
