import unittest
import app

class BrandMarkTests(unittest.TestCase):
    def test_brand_has_custom_vector_mark_beside_title(self):
        demo=app.build_app()
        header=next(c['props']['value'] for c in demo.config['components']
                    if c['type']=='html' and 'id="mainTitle"' in c['props'].get('value',''))
        self.assertIn('<svg class="aj-logo"',header)
        self.assertIn('viewBox="0 0 64 64"',header)
        self.assertIn('linearGradient',header)
        self.assertNotIn('▂▆█▅▂',header)
        self.assertLess(header.index('class="aj-logo"'),header.index('id="mainTitle"'))

    def test_dj_options_offer_the_character_picker(self):
        demo = app.build_app()
        components = demo.config['components']
        self.assertTrue(any(c['props'].get('elem_id') == 'djOptionsPanel' for c in components))
        markdown_values = [c['props'].get('value', '') for c in components if c['type'] == 'markdown']
        self.assertTrue(any('DJ options' in v for v in markdown_values))
        self.assertFalse(any('Coming soon.' in v for v in markdown_values),
                         'The coming-soon placeholder must be replaced by the real picker')
        radios = [c for c in components if c['type'] == 'radio' and c['props'].get('label') == 'DJ character']
        self.assertEqual(len(radios), 1)
        choices = radios[0]['props']['choices']
        self.assertEqual([c[0] for c in choices],
                         ['Off', 'Classic radio', 'Late-night chill', 'Party hype'])
        self.assertEqual(radios[0]['props']['value'], 'classic')
        hint = next(v for v in markdown_values if 'each character changes personality' in v)
        self.assertIn('Upload a custom voice in the Create tab.', hint)

if __name__=='__main__': unittest.main()
