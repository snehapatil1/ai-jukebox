"""Open the existing local jukebox, or start one instance and await readiness.

Kills any stale process holding the server port before launching or reusing."""
import json
from pathlib import Path
import platform
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


def _kill_on_windows(pid):
    """Send SIGTERM via taskkill on Windows."""
    try:
        subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
    except Exception:
        pass


def _kill_on_unix(pid):
    """Send SIGTERM on Unix-like systems."""
    try:
        subprocess.run(['kill', '-TERM', str(pid)], capture_output=True)
    except Exception:
        pass


def kill_stale_port_process():
    """Find and kill any non-gradio process holding PORT."""
    os_name = platform.system()
    killed_pids = []

    if os_name == 'Windows':
        r = subprocess.run(
            ['netstat', '-ano'], capture_output=True, text=True
        )
        for line in r.stdout.splitlines():
            if f':{PORT}' in line and 'LISTENING' in line:
                parts = line.strip().split()
                pid = parts[-1] if parts else None
                if pid and pid.isdigit() and int(pid) != 0:
                    # Check it's not our own Gradio
                    try:
                        with open(f'/proc/{pid}/cmdline', 'rb') as f:
                            cmd = f.read().decode('utf-8', errors='ignore')
                        if 'app.py' not in cmd and 'gradio' not in cmd.lower():
                            _kill_on_windows(int(pid))
                            killed_pids.append(pid)
                    except (FileNotFoundError, PermissionError):
                        # On Windows /proc doesn't exist; kill anyway
                        _kill_on_windows(int(pid))
                        killed_pids.append(pid)
    else:
        r = subprocess.run(
            ['lsof', '-i', f':{PORT}', '-t'], capture_output=True, text=True
        )
        for pid_str in r.stdout.strip().splitlines():
            if pid_str.isdigit():
                _kill_on_unix(int(pid_str))
                killed_pids.append(pid_str)

    return killed_pids


def is_jukebox_running():
    try:
        with urlopen(URL + '/config', timeout=2) as response:
            return json.load(response).get('title') == 'AI Jukebox'
    except (OSError, ValueError):
        return False


def wait_for_cleared(timeout=5):
    """Wait up to `timeout` seconds for PORT to become free."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection((HOST, PORT), timeout=0.5)
            time.sleep(0.2)
        except OSError:
            return True
    return False


def main():
    # Always check for and clean up stale processes first
    killed = kill_stale_port_process()
    if killed:
        print(f'Killed {len(killed)} stale process(es) holding port {PORT}', flush=True)
        time.sleep(1)
        if not wait_for_cleared(5):
            print('Port still occupied after cleanup — aborting.', flush=True)
            return 1

    if is_jukebox_running():
        print(f'AI Jukebox is already running. Opening {URL}', flush=True)
        webbrowser.open(URL)
        return 0

    # Port may be briefly open from a just-started gradio before /config responds
    try:
        socket.create_connection((HOST, PORT), timeout=1)
        # A just-starting app may have bound its port before /config is ready.
        for _ in range(10):
            if is_jukebox_running():
                webbrowser.open(URL)
                return 0
            time.sleep(0.5)
        print(f'Port {PORT} is occupied by an unrecognized or unready service.', flush=True)
        return 1
    except OSError:
        pass

    print(f'Starting AI Jukebox at {URL}. Keep this window open; Ctrl+C stops this instance.', flush=True)
    child = subprocess.Popen([sys.executable, str(ROOT / 'app.py')], cwd=ROOT)
    try:
        for _ in range(90):
            if child.poll() is not None:
                print('The app exited before startup completed. See the error above.', flush=True)
                return child.returncode or 1
            if is_jukebox_running():
                print(f'Ready: {URL}', flush=True)
                webbrowser.open(URL)
                return child.wait()
            time.sleep(1)
        print('Startup is taking longer than expected. See the server output above.', flush=True)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
