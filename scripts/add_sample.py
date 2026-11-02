"""Turn a locally generated song into a bundled sample.

Usage (from the repository root):

    python scripts/add_sample.py "<song id or title>"

The song is looked up in ``data/library.json`` by id first, then by exact
title, then by a unique case-insensitive title match. Its MP3 and cover PNG
are copied into ``samples/audio/`` and ``samples/covers/`` (tracked in git,
so they ship in the submission ZIP) and its metadata is appended to
``samples/samples.json``; the sample keeps the song's id as its fixed id.

Safety:
- Only the song's own audio and cover files are copied. Voice references,
  DJ clips, or any other files under ``data/`` are never touched.
- Re-running for the same song replaces its existing manifest entry and
  files in place (no duplicate ids, no orphaned entries).
- Refuses to run when the song's audio or cover file is missing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ASSET_SUBDIRS = ("audio", "covers")

MANIFEST_FIELDS = (
    "id", "title", "style", "mood", "duration_sec", "instrumental",
    "theme", "lyrics", "created_by", "cover_prompt", "audio", "cover",
)


def _load_json(path: Path) -> list:
    if not path.is_file():
        print(f"error: {path} does not exist.", file=sys.stderr)
        raise SystemExit(1)
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: could not read {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if not isinstance(raw, list):
        print(f"error: {path} must contain a JSON list.", file=sys.stderr)
        raise SystemExit(1)
    return raw


def _find_song(songs: list, query: str) -> dict:
    """Locate a song by id, exact title, or unique title substring."""
    q = query.strip()
    if not q:
        print("error: pass a song id or title.", file=sys.stderr)
        raise SystemExit(1)
    by_id = [s for s in songs if s.get("id") == q]
    if by_id:
        return by_id[0]
    by_title = [s for s in songs if s.get("title") == q]
    if by_title:
        return by_title[0]
    folded = q.casefold()
    partial = [s for s in songs if folded in (s.get("title") or "").casefold()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        titles = "\n  ".join(f"{s['id']} — {s.get('title')}" for s in partial)
        print(f"error: {q!r} matches several songs:\n  {titles}\n"
              "Pass the exact id or title instead.", file=sys.stderr)
        raise SystemExit(1)
    print(f"error: no song in {songs and 'data/library.json' or ''} matches {q!r}.\n"
          "Songs are stored in data/library.json; generate one from the app first.",
          file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy a generated song from data/ into samples/ and add it "
                    "to samples/samples.json."
    )
    parser.add_argument("song", help="Song id or title from data/library.json")
    parser.add_argument("--library", type=Path, default=None,
                        help="Path to data/library.json (default: repo default)")
    parser.add_argument("--samples-dir", type=Path, default=None,
                        help="Path to the samples/ folder (default: repo default)")
    args = parser.parse_args()

    library_file = args.library or (ROOT / "data" / "library.json")
    samples_dir = args.samples_dir or (ROOT / "samples")
    audio_dir = samples_dir / "audio"
    covers_dir = samples_dir / "covers"
    manifest = samples_dir / "samples.json"

    song = _find_song(_load_json(library_file), args.song)

    sample_id = str(song.get("id") or "").strip()
    if not sample_id:
        print("error: the song record has no id.", file=sys.stderr)
        return 1
    audio_rel = str(song.get("audio_path") or "")
    cover_rel = str(song.get("cover_path") or "")
    if not audio_rel:
        print(f"error: song {sample_id} has no audio_path.", file=sys.stderr)
        return 1
    audio_src = (ROOT / audio_rel).resolve()
    if not audio_src.is_file():
        print(f"error: audio file is missing: {audio_src}", file=sys.stderr)
        return 1
    if not cover_rel:
        print(f"error: song {sample_id} has no cover — samples must ship with "
              "a cover. Generate one in the app first.", file=sys.stderr)
        return 1
    cover_src = (ROOT / cover_rel).resolve()
    if not cover_src.is_file():
        print(f"error: cover file is missing: {cover_src}", file=sys.stderr)
        return 1
    samples_root = samples_dir.resolve()
    if audio_src.is_relative_to(samples_root) or cover_src.is_relative_to(samples_root):
        print(f"error: song {sample_id} is already a bundled sample "
              "(its assets live in samples/).", file=sys.stderr)
        return 1

    # Copy ONLY the song's own audio and cover into the tracked samples/ tree.
    audio_name = f"{sample_id}{audio_src.suffix}"
    cover_name = f"{sample_id}{cover_src.suffix}"
    audio_dir.mkdir(parents=True, exist_ok=True)
    covers_dir.mkdir(parents=True, exist_ok=True)
    audio_dst = audio_dir / audio_name
    cover_dst = covers_dir / cover_name
    shutil.copy2(audio_src, audio_dst)
    shutil.copy2(cover_src, cover_dst)

    entry = {
        "id": sample_id,
        "title": str(song.get("title") or ""),
        "style": str(song.get("style") or ""),
        "mood": str(song.get("mood") or ""),
        "duration_sec": song.get("duration_sec", 0),
        "instrumental": bool(song.get("instrumental", False)),
        "theme": str(song.get("theme") or ""),
        "lyrics": str(song.get("lyrics") or ""),
        "created_by": str(song.get("created_by") or ""),
        "cover_prompt": str(song.get("cover_prompt") or ""),
        "audio": audio_name,
        "cover": cover_name,
    }

    entries = _load_json(manifest) if manifest.is_file() else []
    index = {str(e.get("id")): i for i, e in enumerate(entries) if isinstance(e, dict)}
    if sample_id in index:
        entries[index[sample_id]] = entry
        action = "updated"
    else:
        entries.append(entry)
        action = "added"
    manifest.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", "utf-8"
    )

    print(f"Sample {action}: {entry['title'] or sample_id} (id {sample_id})")
    print(f"  audio -> {audio_dst}")
    print(f"  cover -> {cover_dst}")
    print(f"  manifest -> {manifest} ({len(entries)} sample(s))")
    print("Commit samples/ (audio, covers, samples.json); the next app start "
          "will pick the sample up automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
