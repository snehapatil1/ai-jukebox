"""DJ character picker unit tests — no network, no live services.

Covers the character registry contract (labels, TTS parameters, personas),
prompt injection, the Chatterbox request body, the DJ cache key scoping,
and the "Off" path (back-to-back playback with no commentary/prefetch).
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


class CharacterRegistryTests(unittest.TestCase):
    def test_registry_order_labels_and_spec_values(self):
        self.assertEqual(list(prompts.DJ_CHARACTERS),
                         ['off', 'classic', 'chill', 'hype'])
        self.assertEqual([c['label'] for c in prompts.DJ_CHARACTERS.values()],
                         ['Off', 'Classic radio', 'Late-night chill', 'Party hype'])
        self.assertEqual(prompts.DJ_DEFAULT_CHARACTER, 'classic')
        # Classic radio: speed 1.0, exaggeration 0.7
        self.assertEqual(prompts.DJ_CHARACTERS['classic']['speed'], 1.0)
        self.assertEqual(prompts.DJ_CHARACTERS['classic']['exaggeration'], 0.7)
        # Late-night chill: speed 0.9, exaggeration 0.3
        self.assertEqual(prompts.DJ_CHARACTERS['chill']['speed'], 0.9)
        self.assertEqual(prompts.DJ_CHARACTERS['chill']['exaggeration'], 0.3)
        # Party hype: speed 1.15, exaggeration 1.5
        self.assertEqual(prompts.DJ_CHARACTERS['hype']['speed'], 1.15)
        self.assertEqual(prompts.DJ_CHARACTERS['hype']['exaggeration'], 1.5)

    def test_tts_values_stay_in_server_range(self):
        for cid, c in prompts.DJ_CHARACTERS.items():
            self.assertTrue(0.25 <= c['speed'] <= 4.0, cid)
            self.assertGreaterEqual(c['exaggeration'], 0.0, cid)

    def test_personas_present_and_distinct(self):
        for cid in ('classic', 'chill', 'hype'):
            self.assertTrue(prompts.DJ_CHARACTERS[cid]['persona'].strip(), cid)
        self.assertEqual(prompts.DJ_CHARACTERS['off']['persona'], '')
        personas = {prompts.DJ_CHARACTERS[cid]['persona'] for cid in ('classic', 'chill', 'hype')}
        self.assertEqual(len(personas), 3)


class PromptTests(unittest.TestCase):
    def test_system_prompt_keeps_dj_rules_and_injects_persona(self):
        for cid in ('classic', 'chill', 'hype'):
            system = prompts.DJ_SYSTEM.format(persona=prompts.DJ_CHARACTERS[cid]['persona'])
            self.assertIn(prompts.DJ_CHARACTERS[cid]['persona'], system)
            lowered = system.lower()
            self.assertIn('exactly 2-3 sentences', lowered)
            self.assertIn('must mention both songs', lowered)
            self.assertIn('no markdown', lowered)

    def test_dj_commentary_injects_persona_and_both_songs(self):
        prev, nxt = _song('a', 'Prev Song'), _song('b', 'Next Song')
        with patch.object(service.clients, 'qwen_chat_with_fallback',
                          return_value='Nice segue.') as qwen:
            service.dj_commentary(prev, nxt, 'chill')
        system, user = qwen.call_args.args
        self.assertIn('calm, warm, unhurried', system)
        self.assertIn('Prev Song', user)
        self.assertIn('Next Song', user)


class SpeakTests(unittest.TestCase):
    def test_speak_sends_speed_and_exaggeration_and_never_a_server_voice(self):
        calls = {}

        def fake_post(path, json_body=None, timeout=None):
            calls['path'] = path
            calls['body'] = json_body
            return SimpleNamespace(content=b'audio')

        with patch.object(clients._tts, 'post', side_effect=fake_post):
            clients.speak('Line.', speed=1.15, exaggeration=1.5)
        self.assertEqual(calls['path'], '/v1/audio/speech')
        self.assertEqual(calls['body']['speed'], 1.15)
        self.assertEqual(calls['body']['exaggeration'], 1.5)
        self.assertNotIn('voice', calls['body'],
                         'Only the bundled default voice or ref_audio may be used')
        self.assertNotIn('ref_audio', calls['body'])

    def test_speak_defaults_to_speed_1_exaggeration_0(self):
        calls = {}

        def fake_post(path, json_body=None, timeout=None):
            calls['body'] = json_body
            return SimpleNamespace(content=b'audio')

        with patch.object(clients._tts, 'post', side_effect=fake_post):
            clients.speak('Line.')
        self.assertEqual(calls['body']['speed'], 1.0)
        self.assertEqual(calls['body']['exaggeration'], 0.0)


class RenderAndCacheTests(unittest.TestCase):
    def test_render_dj_clip_applies_character_tts_params(self):
        with patch.object(service.clients, 'speak', return_value=b'mp3') as speak:
            service.render_dj_clip('Hello there.', None, 'chill')
        kwargs = speak.call_args.kwargs
        self.assertEqual(kwargs['speed'], 0.9)
        self.assertEqual(kwargs['exaggeration'], 0.3)
        self.assertIsNone(kwargs.get('ref_audio_b64'))

    def test_resolve_character_safe_fallbacks(self):
        self.assertEqual(service.resolve_character('classic'), 'classic')
        self.assertEqual(service.resolve_character('chill'), 'chill')
        self.assertEqual(service.resolve_character('hype'), 'hype')
        self.assertEqual(service.resolve_character('off'), 'classic')
        self.assertEqual(service.resolve_character('bogus'), 'classic')
        self.assertEqual(service.resolve_character(None), 'classic')

    def test_character_is_part_of_the_dj_cache_key(self):
        prev, nxt = _song('a', 'Alpha'), _song('b', 'Beta')
        key = ('a', 'b', 'default', 'hype')
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(service.config, 'DJ_DIR', Path(tmp)), \
                 patch.object(service.config, 'ROOT', Path(tmp)), \
                 patch.object(service, 'dj_commentary',
                              return_value='Two sentences here. Nice.') as comm, \
                 patch.object(service, 'render_dj_clip', return_value=b'mp3') as render:
                service.prefetch_dj_clip(prev, nxt, 'default', None, 'hype')
                event = service._DJ_EVENTS.get(key)
                self.assertIsNotNone(event,
                                     'prefetch must register the character-scoped event')
                self.assertTrue(event.wait(timeout=5))
                entry = service._DJ_CACHE.get(key)
                self.assertIsNotNone(entry, 'cache must be keyed by character too')
                self.assertTrue(entry.get('clip'))
                comm.assert_called_once_with(prev, nxt, 'hype')
                render.assert_called_once_with(comm.return_value, None, 'hype')
                service._DJ_CACHE.pop(key, None)
                service._DJ_EVENTS.pop(key, None)


class OffModeTests(unittest.TestCase):
    def _library(self, tmp):
        library = SongLibrary(Path(tmp) / 'library.json')
        a = library.add(title='A', style='Pop', mood='Calm', duration_sec=30, instrumental=True)
        b = library.add(title='B', style='Pop', mood='Calm', duration_sec=30, instrumental=True)
        return library, a, b

    def test_off_skips_prefetch_and_plays_back_to_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, a, b = self._library(tmp)
            with patch.object(app, 'LIBRARY', library), \
                 patch.object(app.service, 'cover_display_path',
                              return_value=Path(tmp) / 'cover.png'), \
                 patch.object(app.service, 'prefetch_dj_clip') as prefetch, \
                 patch.object(app.service, 'wait_dj_clip') as wait:
                state = {'queue': [a.id, b.id], 'pos': 0, 'mode': 'song'}
                result = app.advance(dict(state), {}, 'off')
            self.assertEqual(result[-1]['mode'], 'song')
            self.assertEqual(result[-1]['pos'], 1)
            prefetch.assert_not_called()
            wait.assert_not_called()

    def test_character_mode_waits_for_dj_clip_with_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, a, b = self._library(tmp)
            with patch.object(app, 'LIBRARY', library), \
                 patch.object(app.service, 'cover_display_path',
                              return_value=Path(tmp) / 'cover.png'), \
                 patch.object(app.service, 'prefetch_dj_clip'), \
                 patch.object(app.service, 'wait_dj_clip',
                              return_value=(Path(tmp) / 'dj.mp3', 'Nice segue.', '')) as wait:
                state = {'queue': [a.id, b.id], 'pos': 0, 'mode': 'song'}
                result = app.advance(dict(state), {}, 'chill')
            self.assertEqual(result[-1]['mode'], 'dj')
            wait.assert_called_once()
            self.assertEqual(wait.call_args.args[:2], (a, b))
            self.assertEqual(wait.call_args.args[2], 'default')
            self.assertIsNone(wait.call_args.args[3])
            self.assertEqual(wait.call_args.args[4], 'chill')


if __name__ == '__main__':
    unittest.main()
