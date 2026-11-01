import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import app
from jukebox.library import SongLibrary

class LibraryLayoutTests(unittest.TestCase):
    def test_tabs_and_three_columns_are_native_components(self):
        demo=app.build_app()
        components=demo.config['components']
        by_id={c['props'].get('elem_id'):c for c in components}
        for name in ('jukeboxTabs','libraryLayout','libraryPanel','playerPanel','coverArtStudio','libraryGallery'):
            self.assertIn(name,by_id)
        self.assertEqual(by_id['jukeboxTabs']['props']['selected'],'library')
        tabs=[c['props'].get('label') for c in components if c['type']=='tabitem']
        self.assertIn('Create',tabs)
        self.assertIn('Library',tabs)
        self.assertEqual(by_id['libraryGallery']['type'],'gallery')
        self.assertTrue(any(d.fn==app.generate_song for d in demo.fns.values()))
        self.assertTrue(any('stop' in str(d.targets) for d in demo.fns.values()))

    def test_search_results_keep_exact_selection_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            lib=SongLibrary(Path(temp)/'library.json')
            one=lib.add(title='Ocean',style='Pop',mood='Calm',duration_sec=30,instrumental=True)
            two=lib.add(title='Storm',style='Rock',mood='Dark',duration_sec=30,instrumental=True)
            with patch.object(app,'LIBRARY',lib):
                items,ids=app.filter_library('storm')
            self.assertEqual(ids,[two.id])
            self.assertEqual(len(items),1)
            self.assertIn('Storm',items[0][1])

    def test_search_clears_hidden_selection_without_touching_player(self):
        with tempfile.TemporaryDirectory() as temp:
            lib = SongLibrary(Path(temp) / 'library.json')
            one = lib.add(title='Ocean', style='Pop', mood='Calm', duration_sec=30, instrumental=True)
            two = lib.add(title='Storm', style='Rock', mood='Dark', duration_sec=30, instrumental=True)
            with patch.object(app, 'LIBRARY', lib):
                demo = app.build_app()
                search = next(b for b in demo.blocks.values() if getattr(b, 'elem_id', None) == 'libSearchBox')
                event = next(d for d in demo.fns.values() if d.inputs == [search])
                result = event.fn('storm')
                self.assertEqual(len(result), 3, 'Search must also clear the destructive-action selection')
                self.assertEqual(result[0]['selected_index'], None)
                self.assertEqual(result[1], [two.id])
                self.assertIsNone(result[2])
                self.assertEqual(len(event.outputs), 3)
                self.assertIsInstance(event.outputs[2], app.gr.State)
                self.assertFalse(any(getattr(b, 'elem_id', None) in
                    ('nowAudio', 'nowMeta', 'queuePanel') for b in event.outputs))
                app.delete_song(result[2], {'queue': [one.id], 'pos': 0, 'mode': 'song'})
                self.assertIsNotNone(lib.get(one.id))

    def test_browser_load_reads_current_library_after_app_build(self):
        with tempfile.TemporaryDirectory() as temp:
            lib = SongLibrary(Path(temp) / 'library.json')
            with patch.object(app, 'LIBRARY', lib):
                demo = app.build_app()
                song = lib.add(title='Created after build', style='Pop', mood='Calm',
                    duration_sec=30, instrumental=True, theme='Fresh description')
                loads = [d for d in demo.config['dependencies']
                         if any(target[1] == 'load' for target in d['targets'])]
                self.assertEqual(len(loads), 1, 'One atomic per-session load must initialize all views')
                handler = demo.fns[loads[0]['id']]
                self.assertEqual(handler.inputs, [])
                result = handler.fn()
                self.assertEqual(len(result), len(handler.outputs))
                self.assertEqual(len(result), 18)
                self.assertEqual(result[0]['selected_index'], 0)
                self.assertEqual(result[1], [song.id])
                self.assertEqual(result[2]['choices'], [(song.display_label(), song.id)])
                self.assertEqual(result[2]['value'], song.id)
                self.assertEqual(result[3], song.id)
                self.assertIn(song.title, result[5])
                self.assertEqual(result[10]['queue'], [song.id])
                self.assertEqual(result[11], 'Fresh description')
                lib.delete(song.id)
                empty = handler.fn()
                self.assertEqual(empty[1], [])
                self.assertIsNone(empty[2]['value'])
                self.assertIsNone(empty[3])
                self.assertEqual(empty[10], app.INITIAL_PLAYER)

    def test_missing_audio_selection_always_returns_seven_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            lib=SongLibrary(Path(temp)/'library.json')
            song=lib.add(title='Missing audio',style='Rock',mood='Dark',duration_sec=30,instrumental=True,audio_path='not-present.wav')
            with patch.object(app,'LIBRARY',lib):
                result=app.select_for_player(song.id,app.INITIAL_PLAYER)
            self.assertEqual(len(result),7)

if __name__=='__main__': unittest.main()
