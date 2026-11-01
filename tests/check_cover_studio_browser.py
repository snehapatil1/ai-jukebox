"""Exercise real Gradio UI with isolated songs and controlled service responses."""
import sys, json, time, tempfile, subprocess, hashlib
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
real=ROOT/'data/library.json'
fingerprint=hashlib.sha256(real.read_bytes()).hexdigest()
scratch_base=Path.home()/'AppData/Local/hermes/cache/scratch'
with tempfile.TemporaryDirectory(prefix='cover-studio-',dir=scratch_base,ignore_cleanup_errors=True) as temp_dir:
    temp=Path(temp_dir)
    with (temp/'server.log').open('w') as log:
        server=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'tests/cover_studio_fixture.py'),str(temp)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(80):
                try:
                    urlopen('http://127.0.0.1:7863',timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.5)
            else:
                raise RuntimeError((temp/'server.log').read_text())
            initial=json.loads((temp/'library.json').read_text())
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1200})
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto('http://127.0.0.1:7863')
                studio=page.locator('#coverArtStudio')
                select=studio.get_by_role('combobox')
                def choose(n):
                    select.click()
                    page.get_by_role('option').filter(has_text=f'Studio track {n}').click()
                    expect(studio.get_by_label('Describe your cover art',exact=True)).to_have_value(f'Hope after storm {n}')
                def prepare():
                    studio.get_by_role('button',name='Improve my description',exact=True).click()
                    expect(studio.get_by_text('Prompt ready',exact=False)).to_be_visible(timeout=15000)
                    if not studio.get_by_label('Final FLUX prompt (editable)',exact=True).is_visible():
                        studio.get_by_text('Inspect / edit final prompt',exact=False).click()
                def generate(text):
                    if not studio.get_by_label('Final FLUX prompt (editable)',exact=True).is_visible():
                        studio.get_by_text('Inspect / edit final prompt',exact=False).click()
                    studio.get_by_label('Final FLUX prompt (editable)',exact=True).fill(text)
                    studio.get_by_role('button',name='Generate new cover',exact=True).click()
                def library():
                    return json.loads((temp/'library.json').read_text())
                # Capture the baseline only after the initial player selection finishes.
                expect(page.locator('#nowMeta')).to_contain_text('Studio track 1', timeout=20000)
                expect(page.locator('#queuePanel')).to_contain_text('Studio track 1', timeout=20000)
                expect(page.locator('#nowAudio').get_by_role('button', name='Play', exact=True)).to_be_visible(timeout=20000)
                expect(page.locator('#nowAudio #duration')).to_have_text('0:30')
                audio_source_before = page.locator('#nowAudio audio[src]').last.get_attribute('src')
                audio_hashes_before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in temp.glob('audio-*.wav')}
                queue_before=page.locator('#queuePanel').inner_text()
                audio_before=page.locator('#nowAudio').inner_text()
                choose(1)
                expect(studio.get_by_label('Describe your cover art',exact=True)).to_have_value('Hope after storm 1')
                prepare()
                edited='Exact user edit: amber seedling. No lettering.'
                generate(edited)
                expect(studio.get_by_text('New cover ready',exact=False)).to_be_visible(timeout=15000)
                assert library()==initial
                calls=[json.loads(x) for x in (temp/'calls.jsonl').read_text().splitlines()]
                assert calls[-1]['prompt']==edited
                studio.get_by_role('button',name='Use this cover',exact=True).click()
                expect(studio.get_by_text('New cover accepted',exact=False)).to_be_visible()
                accepted=library()
                assert accepted[0]['cover_path']!=initial[0]['cover_path']
                assert accepted[0]['cover_prompt']==edited
                for i in range(2):
                    for key in initial[i]:
                        if key not in ('cover_path','cover_prompt'):
                            assert accepted[i][key]==initial[i][key]
                assert accepted[1]==initial[1]
                print('PASS accept: exact edited prompt rendered; only original track cover fields changed')
                prepare(); generate('Reject this candidate')
                expect(studio.get_by_text('New cover ready',exact=False)).to_be_visible()
                studio.get_by_role('button',name='Keep current',exact=True).click()
                expect(studio.get_by_text('Current cover kept.',exact=False)).to_be_visible()
                assert library()==accepted
                print('PASS reject: saved artwork unchanged')
                prepare(); generate('FAIL_REQUEST')
                expect(studio.get_by_text('Current cover unchanged.',exact=False)).to_be_visible(timeout=15000)
                assert library()==accepted
                generate('Recovery candidate')
                expect(studio.get_by_text('New cover ready',exact=False)).to_be_visible(timeout=15000)
                assert library()==accepted
                print('PASS failure + retry: no replacement; recovery preview generated')
                prepare(); generate('SLOW_REQUEST original track one')
                expect(studio.get_by_role('button',name='Keep current',exact=True)).to_be_disabled()
                choose(2)
                time.sleep(5)
                expect(studio.get_by_role('button',name='Keep current',exact=True)).to_be_enabled()
                studio.get_by_role('button',name='Use this cover',exact=True).click()
                expect(studio.get_by_text('No matching candidate',exact=False)).to_be_visible(timeout=15000)
                assert library()==accepted
                assert page.locator('#queuePanel').inner_text()==queue_before, {
                    'queue_before': queue_before,
                    'queue_after': page.locator('#queuePanel').inner_text(),
                    'now_meta': page.locator('#nowMeta').inner_text(),
                }
                assert page.locator('#nowAudio').inner_text()==audio_before
                assert page.locator('#nowAudio audio[src]').last.get_attribute('src') == audio_source_before
                assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in temp.glob('audio-*.wav')} == audio_hashes_before
                assert not errors,errors
                print('PASS track switch during generation: wrong-track accept blocked; queue/audio DOM unchanged; no page errors')
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=15)
assert hashlib.sha256(real.read_bytes()).hexdigest()==fingerprint
print('PASS real saved library checksum unchanged')
