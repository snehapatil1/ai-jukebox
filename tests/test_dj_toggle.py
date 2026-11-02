"""DJ between-songs toggle unit tests — no network, no live services.

Covers the on/off toggle contract (off = back-to-back playback, no
commentary, no prefetch), the single original DJ personality, the Chatterbox
request body (no voice, default speed), and the DJ cache key shape.
"""
import os

os.environ['GRADIO_ANALYTICS_ENABLED'] = 'False'
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
from jukebox import clients, prompts, service
from jukebox.library import Song, SongLibrary


def _song(sid: str = 's1', title: str = 'Prev', style: str = 'Rock',
          mood: str = 'Dark', theme: str = 'rain') -> Song:
    return Song(id=sid, title=title, style=style, mood=mood,
                duration_sec=30, instrumental=False, theme=theme, lyrics='')


class PromptTests(unittest.TestCase):
    def test_single_original_dj_personality(self):
        # One personality only: warm, energetic DJ; no character slots left.
        self.assertNotIn('{persona}', prompts.DJ_SYSTEM)
        self.assertIn('warm, energetic DJ', prompts.DJ_SYSTEM)
        self.assertIn('exactly 2-3 sentences', prompts.DJ_SYSTEM.lower())
        self.assertIn('must mention both songs', prompts.DJ_SYSTEM.lower())

    def test_dj_commentary_injects_both_songs(self):
        prev, nxt = _song('a', 'Prev Song'), _song('b', 'Next Song')
        with patch.object(service.clients, 'qwen_chat_with_fallback',
                          return_value='Nice segue.') as qwen:
            service.dj_commentary(prev, nxt)
        system, user = qwen.call_args.args
        self.assertEqual(system, prompts.DJ_SYSTEM)
        self.assertIn('Prev Song', user)
        self.assertIn('Next Song', user)


class SpeakTests(unittest.TestCase):
    def test_speak_sends_default_speed_and_never_a_server_voice(self):
        calls = {}

        def fake_post(path, json_body=None, timeout=None):
            calls['body'] = json_body
            return SimpleNamespace(content=b'audio')

        with patch.object(clients._tts, 'post', side_effect=fake_post):
            clients.speak('Line.')
        self.assertEqual(calls['body']['speed'], 1.0)
        self.assertNotIn('exaggeration', calls['body'])
        self.assertNotIn('voice', calls['body'],
                         'Only the bundled default voice or ref_audio may be used')
        self.assertNotIn('ref_audio', calls['body'])

    def test_render_dj_clip_uses_default_voice_without_extra_tts_params(self):
        with patch.object(service.clients, 'speak', return_value=b'mp3') as speak:
            service.render_dj_clip('Hello there.', None)
        kwargs = speak.call_args.kwargs
        self.assertEqual(kwargs.get('ref_audio_b64'), None)
        self.assertNotIn('speed', kwargs)
        self.assertNotIn('exaggeration', kwargs)
        self.assertNotIn('voice_id', kwargs)


class CacheTests(unittest.TestCase):
    def test_dj_cache_key_is_song_pair_and_voice(self):
        prev, nxt = _song('a', 'Alpha'), _song('b', 'Beta')
        key = ('a', 'b', 'default')
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(service.config, 'DJ_DIR', Path(tmp)), \
                 patch.object(service.config, 'ROOT', Path(tmp)), \
                 patch.object(service, 'dj_commentary',
                              return_value='Two sentences here. Nice.') as comm, \
                 patch.object(service, 'render_dj_clip', return_value=b'mp3') as render:
                service.prefetch_dj_clip(prev, nxt, 'default', None)
                event = service._DJ_EVENTS.get(key)
                self.assertIsNotNone(event, 'prefetch must register the (pair, voice) event')
                self.assertTrue(event.wait(timeout=5))
                entry = service._DJ_CACHE.get(key)
                self.assertIsNotNone(entry)
                self.assertTrue(entry.get('clip'))
                comm.assert_called_once_with(prev, nxt)
                render.assert_called_once_with(comm.return_value, None)
                service._DJ_CACHE.pop(key, None)
                service._DJ_EVENTS.pop(key, None)


class ToggleModeTests(unittest.TestCase):
    def _library(self, tmp):
        library = SongLibrary(Path(tmp) / 'library.json')
        a = library.add(title='A', style='Pop', mood='Calm', duration_sec=30, instrumental=True)
        b = library.add(title='B', style='Pop', mood='Calm', duration_sec=30, instrumental=True)
        return library, a, b

    def test_toggle_off_plays_back_to_back_without_dj(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, a, b = self._library(tmp)
            with patch.object(app, 'LIBRARY', library), \
                 patch.object(app.service, 'cover_display_path',
                              return_value=Path(tmp) / 'cover.png'), \
                 patch.object(app.service, 'prefetch_dj_clip') as prefetch, \
                 patch.object(app.service, 'wait_dj_clip') as wait:
                state = {'queue': [a.id, b.id], 'pos': 0, 'mode': 'song'}
                result = app.advance(dict(state), {}, False)
            self.assertEqual(result[-1]['mode'], 'song')
            self.assertEqual(result[-1]['pos'], 1)
            prefetch.assert_not_called()
            wait.assert_not_called()

    def test_toggle_on_waits_for_dj_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, a, b = self._library(tmp)
            with patch.object(app, 'LIBRARY', library), \
                 patch.object(app.service, 'cover_display_path',
                              return_value=Path(tmp) / 'cover.png'), \
                 patch.object(app.service, 'prefetch_dj_clip'), \
                 patch.object(app.service, 'wait_dj_clip',
                              return_value=(Path(tmp) / 'dj.mp3', 'Nice segue.', '')) as wait:
                state = {'queue': [a.id, b.id], 'pos': 0, 'mode': 'song'}
                result = app.advance(dict(state), {}, True)
            self.assertEqual(result[-1]['mode'], 'dj')
            wait.assert_called_once()
            self.assertEqual(wait.call_args.args[:2], (a, b))
            self.assertEqual(wait.call_args.args[2], 'default')
            self.assertIsNone(wait.call_args.args[3])


if __name__ == '__main__':
    unittest.main()
