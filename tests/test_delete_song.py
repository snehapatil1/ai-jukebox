"""Deletion regressions use an isolated library; never touch saved songs."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from jukebox.library import SongLibrary

class DeleteSongTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.library = SongLibrary(Path(self.tmp.name) / 'library.json')
        self.songs = [self.library.add(title=f'Test {i}',style='Pop',mood='Calm',duration_sec=30,instrumental=True) for i in range(3)]
        self.patcher = patch.object(app, 'LIBRARY', self.library)
        self.patcher.start()
        self.cover = patch.object(app.service, 'cover_display_path', return_value=Path(self.tmp.name)/'cover.png')
        self.cover.start()
    def tearDown(self):
        self.cover.stop()
        self.patcher.stop()
        self.tmp.cleanup()
    def test_second_delete_without_selection_keeps_surviving_tiles(self):
        state = dict(app.INITIAL_PLAYER)
        first = app.delete_song(self.songs[0].id, state)
        self.assertEqual(len(first[2]['value']),2)
        second = app.delete_song(None, state)
        # A no-op may leave the gallery unchanged or explicitly refresh it.
        self.assertTrue('value' not in second[2] or len(second[2]['value'])==2,
                        'An empty selection erased the remaining gallery tiles')
        self.assertEqual(len(SongLibrary(self.library.path).all()),2)
    def test_stale_selection_keeps_library(self):
        result=app.delete_song('already-deleted',dict(app.INITIAL_PLAYER))
        self.assertTrue('value' not in result[2] or len(result[2]['value'])==3)
    def test_failure_keeps_library(self):
        with patch.object(self.library,'delete',return_value=False):
            result=app.delete_song(self.songs[0].id,dict(app.INITIAL_PLAYER))
        self.assertTrue('value' not in result[2] or len(result[2]['value'])==3)

if __name__=='__main__': unittest.main()
