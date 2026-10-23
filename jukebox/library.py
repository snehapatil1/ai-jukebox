"""Song library with JSON persistence.

Songs live on disk under ``data/`` (gitignored) and are tracked in
``data/library.json`` with paths relative to the repository root, so the app
has no dependency on absolute machine paths and survives server restarts.
"""
from __future__ import annotations

import hashlib
import html
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config

_LOCK = threading.Lock()


@dataclass
class Song:
    id: str
    title: str
    style: str
    mood: str
    duration_sec: float
    instrumental: bool
    theme: str = ""
    lyrics: str = ""
    audio_path: str = ""            # repo-relative, e.g. "data/audio/x.mp3"
    cover_path: str | None = None   # repo-relative or None
    cover_prompt: str = ""          # human-editable cover description stored for regeneration
    created_by: str = ""            # name of the person who generated this song
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def abs_audio(self) -> Path:
        return config.ROOT / self.audio_path

    @property
    def abs_cover(self) -> Path | None:
        return config.ROOT / self.cover_path if self.cover_path else None

    def display_label(self) -> str:
        kind = "instrumental" if self.instrumental else "vocal"
        label = f"{self.title} ({self.style}, {self.mood} - {kind})"
        if self.created_by.strip():
            label += f"\u2014 by {html.escape(self.created_by)}"
        return label


class SongLibrary:
    """Thread-safe JSON-backed collection of songs."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.LIBRARY_FILE
        self._songs: dict[str, Song] = {}
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            self._songs = {s["id"]: Song(**s) for s in raw}
        except (json.JSONDecodeError, KeyError, TypeError) as exc:  # corrupted file
            raise RuntimeError(
                f"Library file {self.path} is corrupted and could not be loaded: {exc}. "
                "Fix or remove it, then restart."
            )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps([asdict(s) for s in self._songs.values()], indent=2),
            "utf-8",
        )
        tmp.replace(self.path)  # atomic-ish write

    # -- access ------------------------------------------------------------
    def all(self) -> list[Song]:
        with _LOCK:
            return list(self._songs.values())

    def get(self, song_id: str) -> Song | None:
        with _LOCK:
            return self._songs.get(song_id)

    def add(self, **fields) -> Song:
        with _LOCK:
            song = Song(id=uuid.uuid4().hex[:12], **fields)
            self._songs[song.id] = song
            self._save()
            return song

    def update(self, song_id: str, **fields) -> Song | None:
        with _LOCK:
            song = self._songs.get(song_id)
            if song is None:
                return None
            for k, v in fields.items():
                setattr(song, k, v)
            self._save()
            return song

    def delete(self, song_id: str) -> bool:
        with _LOCK:
            song = self._songs.pop(song_id, None)
            if song is None:
                return False
            # Remove associated audio file
            if song.audio_path:
                audio_file = config.ROOT / song.audio_path
                try:
                    audio_file.unlink(missing_ok=True)
                except OSError:
                    pass
            # Remove cover art if present
            if song.cover_path:
                cover_file = config.ROOT / song.cover_path
                try:
                    cover_file.unlink(missing_ok=True)
                except OSError:
                    pass
            self._save()
            return True

    @staticmethod
    def rel(path: Path) -> str:
        """Repo-relative string for persistence (portable across machines)."""
        return str(path.relative_to(config.ROOT))

    @staticmethod
    def abs(rel: str) -> Path:
        return config.ROOT / rel
