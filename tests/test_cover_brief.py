import unittest
from unittest.mock import patch
from jukebox import service, prompts
from jukebox.library import Song


class CoverBriefTests(unittest.TestCase):
    def setUp(self):
        self.song = Song(id='test', title='Rain', style='Rock', mood='Melancholic',
                         duration_sec=30, instrumental=False, theme='sad but hopeful storm',
                         lyrics='Gray skies crack\nBut hope remains')

    def test_description_is_translated_with_song_and_explicit_choices(self):
        with patch.object(service.clients, 'qwen_chat_with_fallback', return_value='A lone tree in rain.') as qwen:
            result = service.cover_prompt_for(self.song, user_description='One oak, no people',
                                             artistic_style='Minimal', color_palette='indigo and amber')
        system, context = qwen.call_args.args
        for text in ('sad but hopeful storm', 'Gray skies crack', 'Rock', 'Melancholic',
                     'One oak, no people', 'Minimal', 'indigo and amber'):
            self.assertIn(text, context)
        self.assertNotIn(self.song.title, context)
        for text in ('subject', 'setting', 'composition', 'lighting', 'palette', 'style',
                     'thumbnail', 'lettering', 'signatures'):
            self.assertIn(text, system.lower())
        self.assertIn('A lone tree in rain.', result)
        self.assertIn('indigo and amber', result)
        self.assertIn('Minimal', result)

    def test_edited_final_prompt_is_sent_verbatim_without_qwen(self):
        with patch.object(service.clients, 'qwen_chat_with_fallback') as qwen:
            result = service.cover_prompt_for(self.song, custom_prompt=' My exact edited final prompt. ')
        self.assertEqual(result, 'My exact edited final prompt.')
        qwen.assert_not_called()

    def test_empty_qwen_response_does_not_silently_render(self):
        with patch.object(service.clients, 'qwen_chat_with_fallback', return_value='  '):
            with self.assertRaises(service.PipelineError):
                service.cover_prompt_for(self.song)

if __name__ == '__main__':
    unittest.main()
