import unittest
from unittest.mock import patch
import app
from jukebox import service
from jukebox.library import Song

class PolishTests(unittest.TestCase):
    def test_native_player_is_the_only_play_pause_control(self):
        demo=app.build_app()
        ids={c['props'].get('elem_id'):c for c in demo.config['components']}
        self.assertNotIn('playBtn', ids)
        self.assertIn('nowAudio', ids)
        self.assertIn('skipBtn', ids)
        values=[c['props'].get('value') for c in demo.config['components']]
        self.assertIn('Improve my description', values)
        self.assertNotIn('Prepare visual brief', values)
        for title in ('Current','New preview'):
            image=next(c for c in demo.config['components'] if c['type']=='image' and c['props'].get('label')==title)
            self.assertEqual(image['props']['buttons'], [])
            self.assertFalse(image['props']['show_label'])
            self.assertIn('**'+title+'**', values)
        self.assertNotIn('Your team’s DJ controls will appear here.', str(values))

    def test_styles_have_explicit_different_medium_requirements(self):
        song=Song(id='test',title='Rain',style='Rock',mood='Melancholic',duration_sec=30,instrumental=False)
        for style,terms in {'Photo':['photographic','lens'],
                            'Illustration':['drawn','painted'],
                            'Minimal':['simplified forms','limited detail','negative space'],
                            'Abstract':['nonliteral','shapes']}.items():
            with self.subTest(style=style), patch.object(service.clients,'qwen_chat_with_fallback',return_value='A rain scene.') as qwen:
                brief=service.cover_prompt_for(song,user_description='rain',artistic_style=style)
                for term in terms:
                    self.assertIn(term,brief.lower())
                    self.assertIn(term,qwen.call_args.args[1].lower())

if __name__=='__main__':unittest.main()
