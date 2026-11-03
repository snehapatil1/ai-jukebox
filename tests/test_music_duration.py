"""A quiet ending must survive the music download without being trimmed."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from jukebox import clients


class MusicDurationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is required for audio regression')
    def test_download_preserves_full_render_including_quiet_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'render.mp3'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=8', '-af', 'apad=pad_dur=2',
                            str(path)], check=True)
            rendered = path.read_bytes()
        responses = [
            SimpleNamespace(json=lambda: {'data': {'task_id': 'test'}}),
            SimpleNamespace(json=lambda: {'data': [{'status': 1, 'result': json.dumps(
                [{'status': 1, 'file': '/v1/audio?path=test', 'metas': {}}])}]}),
        ]
        with patch.object(clients._music, 'post', side_effect=responses) as post, \
             patch.object(clients._music, 'get', return_value=SimpleNamespace(content=rendered)):
            actual, _ = clients.generate_music('calm instrumental', duration_sec=10, poll_interval=0)
        self.assertEqual(post.call_args_list[0].kwargs['json_body']['audio_duration'], 10)
        self.assertEqual(actual, rendered, 'Do not shorten the selected duration by trimming quiet audio')
