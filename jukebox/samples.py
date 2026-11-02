"""Bundled sample songs loaded from the tracked ``samples/`` folder.

Generated songs live in ``data/`` (gitignored), so a fresh clone starts with
an empty library. The assignment requires three ready-to-play sample songs
(title + cover) to ship in the GitHub ZIP: they live under ``samples/``
(tracked in git) and are registered into the library at startup — in
place, matched by their fixed id, without copying anything into ``data/``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import config

log = logging.getLogger("jukebox.samples")


def load_samples(library, samples_dir: Path | None = None) -> int:
    """Register sample songs that are not already in the library.

    *library* is a :class:`jukebox.library.SongLibrary`. *samples_dir*
    defaults to ``config.SAMPLES_DIR`` (the repo ``samples/`` folder) and must
    contain ``samples.json`` plus ``audio/`` and ``covers/`` subfolders.

    Each manifest entry is matched by its fixed ``id`` — entries whose id is
    already present are left untouched, so re-running (e.g. a server restart)
    never creates duplicates. Entries whose audio or cover file is missing are
    skipped with a logged warning.

    Returns the number of samples newly added.
    """
    samples_dir = samples_dir or config.SAMPLES_DIR
    manifest = samples_dir / "samples.json"
    if not manifest.is_file():
        log.warning("No samples manifest at %s — skipping sample loading", manifest)
        return 0
    try:
        entries = json.loads(manifest.read_text("utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read samples manifest %s: %s", manifest, exc)
        return 0
    if not isinstance(entries, list):
        log.warning("Samples manifest %s must contain a JSON list; skipping", manifest)
        return 0

    added = 0
    for entry in entries:
        if not isinstance(entry, dict):
            log.warning("Ignoring non-object entry in %s", manifest)
            continue
        try:
            sample_id = str(entry["id"]).strip()
            if not sample_id:
                log.warning("Sample entry without an id in %s — skipped", manifest)
                continue
            if library.get(sample_id) is not None:
                continue  # already registered; keep ids unique
            # Filenames only (the sample's own audio/ and covers/ subfolders).
            audio_name = Path(str(entry.get("audio") or "")).name
            cover_name = Path(str(entry.get("cover") or "")).name
            if not audio_name:
                log.warning("Sample %s has no audio filename — skipped", sample_id)
                continue
            if not cover_name:
                log.warning("Sample %s has no cover filename — skipped", sample_id)
                continue
            audio_fp = samples_dir / "audio" / audio_name
            cover_fp = samples_dir / "covers" / cover_name
            if not audio_fp.is_file():
                log.warning(
                    "Sample %s skipped: audio file missing (%s)", sample_id, audio_fp
                )
                continue
            if not cover_fp.is_file():
                log.warning(
                    "Sample %s skipped: cover file missing (%s)", sample_id, cover_fp
                )
                continue
            library.add(
                id=sample_id,
                title=str(entry.get("title") or sample_id),
                style=str(entry.get("style") or ""),
                mood=str(entry.get("mood") or ""),
                duration_sec=float(entry.get("duration_sec") or 0.0),
                instrumental=bool(entry.get("instrumental", False)),
                theme=str(entry.get("theme") or ""),
                lyrics=str(entry.get("lyrics") or ""),
                created_by=str(entry.get("created_by") or ""),
                cover_prompt=str(entry.get("cover_prompt") or ""),
                audio_path=str(audio_fp.relative_to(config.ROOT)),
                cover_path=str(cover_fp.relative_to(config.ROOT)),
            )
            added += 1
            log.info("Registered bundled sample song %r (%s)", sample_id, manifest)
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("Sample entry %r in %s is invalid (%s) — skipped",
                        entry.get("id"), manifest, exc)
    return added
