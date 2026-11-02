"""Cover Studio UI contracts, with isolated storage and no network calls."""
import os
import sys
os.environ['GRADIO_ANALYTICS_ENABLED'] = 'False'
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from jukebox.library import SongLibrary


class CoverStudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library = SongLibrary(self.root / 'library.json')
        self.song = self.library.add(title='Moon tide', style='Pop', mood='Dreamy',
            duration_sec=30, instrumental=False, theme='Ocean at night', lyrics='Moon above',
            audio_path='song.mp3', cover_path='old.png', cover_prompt='Old brief')
        self.other = self.library.add(title='Other', style='Rock', mood='Dark',
            duration_sec=40, instrumental=True, cover_prompt='Fallback brief')
        self.before = asdict(self.song)
        self.patches = [patch.object(app, 'LIBRARY', self.library),
                        patch.object(app.config, 'ROOT', self.root),
                        patch.object(app.service, 'cover_display_path',
                                     side_effect=lambda s: self.root / (s.cover_path or 'placeholder.png'))]
        for p in self.patches:
            p.start()
        self.addCleanup(self.tmp.cleanup)
        for p in self.patches:
            self.addCleanup(p.stop)

    def test_prepare_uses_description_style_palette_and_binds_track(self):
        with patch.object(app.service, 'cover_prompt_for', create=True, return_value='Qwen visual brief') as qwen:
            prompt, bound_id, status, candidate, preview = app.prepare_cover_brief(
                self.song.id, 'Silver sea', 'Abstract', 'navy and gold')
        qwen.assert_called_once_with(self.song, user_description='Silver sea',
                                    artistic_style='Abstract', color_palette='navy and gold')
        self.assertEqual(prompt, 'Qwen visual brief')
        self.assertEqual(bound_id, self.song.id)
        self.assertIsNone(candidate)
        self.assertEqual(asdict(self.song), self.before)
        self.assertIn('edit', status.lower())


    def test_generate_uses_edited_final_prompt_verbatim_without_saving(self):
        edited = '  Hand-edited final prompt\nwith exact spacing  '
        with patch.object(app.service, 'generate_cover', return_value=(self.root / 'new.png', edited)) as flux, \
             patch.object(app.service, 'cover_prompt_for', create=True) as qwen:
            preview, candidate, status = app.generate_cover_candidate(self.song.id, self.song.id, edited)
        flux.assert_called_once_with(self.song, custom_prompt=edited)
        qwen.assert_not_called()
        self.assertEqual(preview, str(self.root / 'new.png'))
        self.assertEqual(candidate, {'song_id': self.song.id, 'path': str(self.root / 'new.png'), 'prompt': edited})
        self.assertEqual(asdict(self.song), self.before)
        self.assertIn('accept', status.lower())

    def test_generate_rejects_unprepared_blank_deleted_and_wrong_track(self):
        with patch.object(app.service, 'generate_cover') as flux:
            for sid, bound, prompt in [(self.song.id, None, 'brief'),
                    (self.other.id, self.song.id, 'brief'),
                    (self.song.id, self.song.id, '  '), ('deleted', 'deleted', 'brief')]:
                with self.subTest(sid=sid, bound=bound, prompt=prompt):
                    preview, candidate, status = app.generate_cover_candidate(sid, bound, prompt)
                    self.assertIsNone(candidate)
            flux.assert_not_called()
        self.assertEqual(asdict(self.song), self.before)


    def test_accept_updates_only_cover_fields_and_requires_matching_track(self):
        candidate = {'song_id': self.song.id, 'path': str(self.root / 'new.png'), 'prompt': 'Edited'}
        result = app.accept_cover_candidate(self.other.id, candidate)
        self.assertEqual(asdict(self.song), self.before)
        self.assertIn('selection', result[3].lower())
        result = app.accept_cover_candidate(self.song.id, candidate)
        expected = dict(self.before, cover_path='new.png', cover_prompt='Edited')
        self.assertEqual(asdict(self.song), expected)
        self.assertEqual(asdict(SongLibrary(self.library.path).get(self.song.id)), expected)
        self.assertIsNone(result[2])
        self.assertEqual(result[0], str(self.root / 'new.png'))

    def test_keep_current_discards_candidate_without_saving(self):
        self.assertEqual(app.keep_current_cover(), (None, None, 'Current cover kept. New candidate discarded.'))
        self.assertEqual(asdict(self.song), self.before)

    def test_selection_prefills_description_and_invalidates_old_work(self):
        result = app.select_cover_track(self.song.id)
        self.assertEqual(result[:6], ('Ocean at night', str(self.root / 'old.png'), None, '', None, None))
        self.assertEqual(app.select_cover_track(self.other.id)[0], 'Fallback brief')
        self.assertEqual(app.select_cover_track('deleted')[:6], ('', None, None, '', None, None))

    def test_prepare_and_generate_failures_keep_saved_cover_intact(self):
        with patch.object(app.service, 'cover_prompt_for', create=True, side_effect=TimeoutError), \
             patch.object(app.service, 'generate_cover', side_effect=TimeoutError), \
             self.assertLogs(app.LOG, level='ERROR'):
            prepared = app.prepare_cover_brief(self.song.id, '', 'Photo', '')
            generated = app.generate_cover_candidate(self.song.id, self.song.id, 'Final')
        self.assertIsNone(prepared[1])
        self.assertIsNone(generated[1])
        self.assertIn('unchanged', prepared[2])
        self.assertIn('unchanged', generated[2])
        self.assertEqual(asdict(self.song), self.before)


    def test_render_yields_generating_status_before_calling_flux(self):
        edited = '  Exact final prompt\nunchanged  '
        with patch.object(app.service, 'generate_cover', return_value=(self.root / 'new.png', edited)) as flux:
            updates = app.render_cover_candidate(self.song.id, self.song.id, edited)
            first = next(updates)
            self.assertIn('Generating', first[2])
            self.assertEqual(first[:2], (None, None))
            flux.assert_not_called()
            final = next(updates)
            flux.assert_called_once_with(self.song, custom_prompt=edited)
            self.assertEqual(final[1]['prompt'], edited)
            self.assertEqual(list(updates), [])
        self.assertEqual(asdict(self.song), self.before)

    def test_keep_current_disabled_for_entire_cover_render_chain(self):
        demo = app.build_app()
        components = demo.config['components']
        generate = next(c['id'] for c in components if c['props'].get('value') == 'Generate new cover')
        keep = next(c['id'] for c in components if c['props'].get('value') == 'Keep current')
        dependencies = demo.config['dependencies']
        clicked = next(d for d in dependencies if [generate, 'click'] in d['targets'] or
                       (generate, 'click') in d['targets'])
        disable = demo.fns[clicked['id']]
        self.assertEqual([b._id for b in disable.outputs], [keep],
                         'Disable Keep current before starting image generation')
        self.assertFalse(clicked['queue'])
        self.assertEqual(disable.fn(), app.gr.update(interactive=False))
        render = next(d for d in dependencies if d['trigger_after'] == clicked['id'])
        self.assertIs(demo.fns[render['id']].fn, app.render_cover_candidate)
        self.assertEqual([b.label for b in demo.fns[render['id']].inputs if not isinstance(b, app.gr.State)],
                         ['Editing cover for', 'Final FLUX prompt (editable)'])
        enabled = next(d for d in dependencies if d['trigger_after'] == render['id'] and
                       d['outputs'] == [keep])
        self.assertFalse(enabled['trigger_only_on_success'])
        self.assertEqual(demo.fns[enabled['id']].fn(), app.gr.update(interactive=True))
        with patch.object(app.service, 'generate_cover', side_effect=TimeoutError), \
             self.assertLogs(app.LOG, level='ERROR'):
            failed = list(app.render_cover_candidate(self.song.id, self.song.id, 'Final'))
        self.assertIsNone(failed[-1][1])
        self.assertIn('unchanged', failed[-1][2])

    def test_native_studio_builds_with_track_choices_editable_prompt_and_safe_outputs(self):
        demo = app.build_app()
        components = demo.config['components']
        by_label = {c['props'].get('label'): c for c in components if c.get('props', {}).get('label')}
        self.assertIn('Editing cover for', by_label)
        track = by_label['Editing cover for']
        self.assertEqual(track['type'], 'dropdown')
        self.assertEqual([choice[1] for choice in track['props']['choices']], [self.song.id, self.other.id])
        self.assertTrue(by_label['Final FLUX prompt (editable)']['props']['interactive'])
        self.assertEqual(by_label['Artistic style']['props']['choices'],
                         [('Photo', 'Photo'), ('Illustration', 'Illustration'), ('Minimal', 'Minimal'), ('Abstract', 'Abstract')])
        self.assertIn('Current', by_label)
        self.assertIn('New preview', by_label)
        self.assertIn('Describe your cover art', by_label)
        self.assertIn('Use this cover', [c['props'].get('value') for c in components])
        self.assertNotIn('🖼️ Retry Cover', [c['props'].get('value') for c in components])
        protected = {c['id'] for c in components if c['props'].get('elem_id') in
                     ('nowAudio', 'nowMeta', 'lyricsSection', 'queuePanel')}
        # The audio player and queue states must not be outputs of any Studio event.
        for block in demo.blocks.values():
            if isinstance(block, app.gr.State) and block.value == app.INITIAL_PLAYER:
                protected.add(block._id)
        studio_fns = {app.prepare_cover_brief, app.render_cover_candidate,
                      app.select_cover_track, app.accept_cover_candidate, app.keep_current_cover}
        seen = set()
        for dependency in demo.fns.values():
            if dependency.fn in studio_fns:
                seen.add(dependency.fn)
                self.assertFalse(protected.intersection(output._id for output in dependency.outputs))
        self.assertEqual(seen, studio_fns)


if __name__ == '__main__':
    unittest.main()
