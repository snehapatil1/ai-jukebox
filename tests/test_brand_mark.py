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

    def test_dj_options_offer_the_on_off_toggle(self):
        demo = app.build_app()
        components = demo.config['components']
        markdown_values = [c['props'].get('value', '') for c in components if c['type'] == 'markdown']
        self.assertTrue(any('### DJ options' in v for v in markdown_values))
        self.assertFalse(any('Coming soon.' in v for v in markdown_values),
                         'The coming-soon placeholder must be replaced by the real control')
        checkboxes = [c for c in components
                      if c['type'] == 'checkbox' and 'DJ between songs' in c['props'].get('label', '')]
        self.assertEqual(len(checkboxes), 1)
        self.assertTrue(checkboxes[0]['props'].get('value', False),
                        'The DJ toggle must be ON by default')
        hint = next(v for v in markdown_values if 'Want the DJ to sound like you?' in v)
        self.assertIn('Upload a custom voice (MP3 or WAV) in the Create tab.', hint)
        # The character picker is gone, and so is the placeholder panel box.
        radios = [c for c in components
                  if c['type'] == 'radio' and 'DJ character' in c['props'].get('label', '')]
        self.assertEqual(radios, [])
        self.assertFalse(any(c['props'].get('elem_id') == 'djOptionsPanel' for c in components))

if __name__=='__main__': unittest.main()
