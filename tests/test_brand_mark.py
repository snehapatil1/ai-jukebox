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

    def test_library_reserves_space_for_teammates_dj_controls(self):
        demo=app.build_app()
        components=demo.config['components']
        self.assertTrue(any(c['props'].get('elem_id')=='djOptionsPanel' for c in components))
        self.assertTrue(any('DJ options' in c['props'].get('value','') for c in components if c['type']=='markdown'))
        self.assertTrue(any('Coming soon.' in c['props'].get('value','') for c in components if c['type']=='markdown'))

if __name__=='__main__': unittest.main()
