"""Start one Jukebox with its virtualenv, or reuse an already healthy instance.

Never terminate an unknown process or a server owned by another launcher.
"""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser

HOST = '127.0.0.1'
PORT = 7860
URL = f'http://{HOST}:{PORT}'
ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def port_is_open():
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


def is_jukebox_running():
    try:
        with urlopen(URL + '/config', timeout=2) as response:
            config = json.load(response)
            return config.get('title') == 'AI Jukebox'
    except (OSError, ValueError):
        return False


def main(open_browser=True):
    def open_ready():
        print(f'AI Jukebox is ready: {URL}', flush=True)
        if open_browser:
            webbrowser.open(URL)

    if is_jukebox_running():
        print('Reusing the running app; playback and current work stay intact.', flush=True)
        open_ready()
        return 0
    if port_is_open():
        # Another double-click may be finishing startup; give it a short grace period.
        for _ in range(6):
            if is_jukebox_running():
                open_ready()
                return 0
            time.sleep(0.5)
        print(f'Port {PORT} is in use by another or unready app. Nothing was stopped. '
              'Close that app yourself or wait for it to finish starting, then try again.', flush=True)
        return 1
    if not PYTHON.is_file():
        print('The project virtual environment is missing. See README.md for setup.', flush=True)
        return 1
    print(f'Starting AI Jukebox at {URL}. Keep this window open; Ctrl+C stops this instance.', flush=True)
    try:
        child = subprocess.Popen([str(PYTHON), str(ROOT / 'app.py')], cwd=ROOT)
    except OSError as exc:
        print(f'Could not start the project Python: {exc}', flush=True)
        return 1
    try:
        for _ in range(90):
            if child.poll() is not None:
                print('The app exited before startup completed. See the error above.', flush=True)
                return child.returncode or 1
            if is_jukebox_running():
                open_ready()
                return child.wait()
            time.sleep(1)
        print('Startup took more than 90 seconds. See the server output above.', flush=True)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        # Only this launcher's own child may be stopped here.
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    raise SystemExit(main(open_browser='--no-browser' not in sys.argv))
