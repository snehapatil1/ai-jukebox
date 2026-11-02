import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import launcher

class LauncherTests(unittest.TestCase):
    def test_running_jukebox_is_reused(self):
        with patch.object(launcher,'is_jukebox_running',return_value=True), patch.object(launcher.webbrowser,'open') as browser, patch.object(launcher.subprocess,'Popen') as spawn:
            self.assertEqual(launcher.main(),0)
            browser.assert_called_once_with(launcher.URL)
            spawn.assert_not_called()
    def test_unknown_listener_is_not_stopped(self):
        with patch.object(launcher,'is_jukebox_running',return_value=False), patch.object(launcher,'port_is_open',return_value=True), patch.object(launcher.subprocess,'Popen') as spawn:
            self.assertEqual(launcher.main(),1)
            spawn.assert_not_called()

if __name__=='__main__': unittest.main()
