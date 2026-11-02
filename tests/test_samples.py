"""Sample-song regressions use isolated temp trees; never touch the repo's
samples/ folder or the user's real data/ library."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jukebox import config  # noqa: E402
from jukebox.library import SongLibrary  # noqa: E402
from jukebox.samples import load_samples  # noqa: E402

MANIFEST = [
    {
        "id": "s1", "title": "Sample One", "style": "Pop", "mood": "Happy",
        "duration_sec": 30, "instrumental": False, "theme": "sunrise drive",
        "lyrics": "[Verse 1]\nlyrics here", "created_by": "Team",
        "cover_prompt": "sunrise over a coastal road", "audio": "s1.mp3",
        "cover": "s1.png",
    },
    {
        "id": "s2", "title": "Sample Two", "style": "Rock", "mood": "Energetic",
        "duration_sec": 45, "instrumental": True, "theme": "", "lyrics": "",
        "created_by": "", "cover_prompt": "", "audio": "s2.mp3", "cover": "s2.png",
    },
    {
        "id": "broken-audio", "title": "Broken Audio", "style": "Jazz",
        "mood": "Calm", "duration_sec": 20, "instrumental": False,
        "theme": "", "lyrics": "", "created_by": "", "cover_prompt": "",
        "audio": "missing.mp3", "cover": "s1.png",
    },
    {
        "id": "broken-cover", "title": "Broken Cover", "style": "Folk",
        "mood": "Calm", "duration_sec": 25, "instrumental": False,
        "theme": "", "lyrics": "", "created_by": "", "cover_prompt": "",
        "audio": "s2.mp3", "cover": "missing.png",
    },
]


class SampleLoaderTests(unittest.TestCase):
    """Each test runs against a tmp tree that mirrors the repo layout:
    ROOT/samples/{audio,covers,samples.json} and ROOT/data/library.json."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.samples = self.root / "samples"
        (self.samples / "audio").mkdir(parents=True)
        (self.samples / "covers").mkdir(parents=True)
        (self.samples / "audio" / "s1.mp3").write_bytes(b"fake-audio-1")
        (self.samples / "audio" / "s2.mp3").write_bytes(b"fake-audio-2")
        (self.samples / "covers" / "s1.png").write_bytes(b"fake-cover-1")
        (self.samples / "covers" / "s2.png").write_bytes(b"fake-cover-2")
        (self.samples / "samples.json").write_text(
            json.dumps(MANIFEST, indent=2), "utf-8")
        self.library = SongLibrary(self.root / "data" / "library.json")
        # Mirror production: SAMPLES_DIR always equals ROOT / "samples".
        self.patchers = [
            patch.object(config, "ROOT", self.root),
            patch.object(config, "SAMPLES_DIR", self.samples),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()
        self.tmp.cleanup()

    def _reload(self):
        """Simulate an app restart: fresh library object from the saved file."""
        return SongLibrary(self.library.path)

    def test_loading_samples_registers_in_place(self):
        added = load_samples(self.library, self.samples)
        self.assertEqual(added, 2)  # the two broken entries are skipped
        song = self.library.get("s1")
        assert song is not None
        self.assertEqual(song.title, "Sample One")
        self.assertEqual(song.audio_path, "samples/audio/s1.mp3")
        self.assertEqual(song.cover_path, "samples/covers/s1.png")
        # Points at the tracked file in place — nothing copied into data/.
        self.assertTrue(song.abs_audio.is_file())
        self.assertFalse((self.root / "data" / "audio" / "s1.mp3").exists())
        self.assertFalse((self.root / "data" / "covers" / "s1.png").exists())

    def test_no_duplicates_on_restart(self):
        load_samples(self.library, self.samples)
        restart = self._reload()
        added = load_samples(restart, self.samples)
        self.assertEqual(added, 0)
        songs = restart.all()
        self.assertEqual(len(songs), 2)
        self.assertEqual(sorted(s.id for s in songs), ["s1", "s2"])

    def test_missing_files_are_skipped_with_warning(self):
        with self.assertLogs("jukebox.samples", level="WARNING") as logs:
            added = load_samples(self.library, self.samples)
        self.assertEqual(added, 2)
        self.assertIsNone(self.library.get("broken-audio"))
        self.assertIsNone(self.library.get("broken-cover"))
        text = " ".join(logs.output)
        self.assertIn("broken-audio", text)
        self.assertIn("missing.mp3", text)
        self.assertIn("broken-cover", text)
        self.assertIn("missing.png", text)

    def test_missing_manifest_is_a_noop(self):
        loaded = load_samples(self.library, self.samples / "nope")
        self.assertEqual(loaded, 0)
        self.assertEqual(self.library.all(), [])

    def test_deleting_a_sample_keeps_its_files(self):
        load_samples(self.library, self.samples)
        audio = self.samples / "audio" / "s1.mp3"
        cover = self.samples / "covers" / "s1.png"
        self.assertTrue(self.library.delete("s1"))
        self.assertIsNone(self.library.get("s1"))
        self.assertTrue(audio.is_file(), "sample audio must not be deleted")
        self.assertTrue(cover.is_file(), "sample cover must not be deleted")
        # The library record is gone from the persisted file; the other
        # sample survives.
        saved = json.loads((self.root / "data" / "library.json").read_text("utf-8"))
        self.assertEqual([s["id"] for s in saved], ["s2"])

    def test_library_add_keeps_explicit_id_but_defaults_generate_one(self):
        fixed = self.library.add(id="fixed-id", title="T", style="Pop",
                                 mood="Calm", duration_sec=30, instrumental=True)
        self.assertEqual(fixed.id, "fixed-id")
        auto = self.library.add(title="T2", style="Pop", mood="Calm",
                                duration_sec=30, instrumental=True)
        self.assertTrue(auto.id != "fixed-id")
        self.assertEqual(len(auto.id), 12)  # default ids are uuid-hex as before


if __name__ == "__main__":
    unittest.main()
