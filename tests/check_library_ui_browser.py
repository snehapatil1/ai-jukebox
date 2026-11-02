"""Read-only live UI acceptance: native selection, tabs, themes, responsive layout."""
import json,time,hashlib
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/library-layout'
OUT.mkdir(parents=True,exist_ok=True)
library=ROOT/'data/library.json'
before=hashlib.sha256(library.read_bytes()).hexdigest()
songs=json.loads(library.read_text())
for _ in range(60):
    try:
        urlopen('http://127.0.0.1:7860/',timeout=1).close(); break
    except OSError: time.sleep(.5)
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1536,'height':1100})
    errors=[]
    media_responses=[]
    page.on('response',lambda response:media_responses.append((response.url,response.status)) if 'gradio_api/file=' in response.url and ('.mp3' in response.url or '.wav' in response.url) else None)
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://127.0.0.1:7860')
    expect(page.get_by_role('tab',name='Library',exact=True)).to_have_attribute('aria-selected','true')
    expect(page.locator('#nowMeta')).to_contain_text(songs[0]['title'],timeout=45000)
    results=[]
    for i in (0,1,2):
        page.locator('#libraryGallery .thumbnail-item').nth(i).click()
        expect(page.locator('#nowMeta')).to_contain_text(songs[i]['title'],timeout=30000)
        expect(page.locator('#libraryGallery .thumbnail-item').nth(i)).to_have_class(__import__('re').compile('selected'))
        expect(page.locator('#coverArtStudio').get_by_label('Describe your cover art',exact=True)).to_have_value(songs[i]['theme'],timeout=10000)
        audio=page.locator('#nowAudio audio[src]').last
        expect(audio).to_have_attribute('src',__import__('re').compile('.+'),timeout=15000)
        src=audio.get_attribute('src')
        assert src
        # Resolve the live source and fetch in one browser task: replacement can revoke a captured blob URL.
        for attempt in range(30):
            loaded = audio.evaluate('async (a)=>{try {if(a.readyState<2)return false;const r=await fetch(a.currentSrc||a.src);return r.status===200;}catch{return false;}}')
            if loaded:
                break
            page.wait_for_timeout(200)
        assert loaded, 'Selected audio did not finish loading'
        assert any(status==200 for url,status in media_responses),media_responses
        assert page.locator('#nowCover img').count()>0
        if songs[i]['lyrics']:
            page.locator('#lyricsSection summary').click()
            expect(page.locator('#lyricsSection')).to_contain_text(songs[i]['lyrics'].splitlines()[0])
            page.locator('#lyricsSection summary').click()
        results.append({'selected':songs[i]['id'],'audio_http':200})
    page.locator('#libraryGallery .thumbnail-item').nth(2).click()
    expect(page.locator('#nowMeta')).to_contain_text(songs[2]['title'])
    page.locator('#libSearchBox textarea').fill(songs[1]['title'])
    expect(page.locator('#libraryGallery .thumbnail-item')).to_have_count(1,timeout=15000)
    page.locator('#libraryGallery .thumbnail-item').first.click()
    expect(page.locator('#nowMeta')).to_contain_text(songs[1]['title'])
    page.locator('#libSearchBox textarea').fill('')
    expect(page.locator('#libraryGallery .thumbnail-item')).to_have_count(len(songs),timeout=15000)
    page.locator('#libraryGallery .thumbnail-item').first.click()
    expect(page.locator('#nowMeta')).to_contain_text(songs[0]['title'])
    page.locator('#themeToggle').click()
    expect(page.locator('html')).to_have_attribute('data-theme','light')
    page.reload()
    expect(page.locator('html')).to_have_attribute('data-theme','light')
    expect(page.locator('#nowMeta')).to_contain_text(songs[0]['title'],timeout=45000)
    page.locator('#themeToggle').click()
    expect(page.locator('html')).to_have_attribute('data-theme','dark')
    dimensions=[]
    for width in (1536,1024,768,390):
        page.set_viewport_size({'width':width,'height':1100})
        page.wait_for_timeout(400)
        boxes=[page.locator('#'+name).bounding_box() for name in ('libraryPanel','playerPanel','coverArtStudio')]
        doc=page.evaluate('({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})')
        assert doc['scroll']<=doc['width']+1,(width,doc)
        if width>1000:
            assert boxes[0]['x']<boxes[1]['x']<boxes[2]['x'],boxes
        else:
            assert boxes[0]['y']<boxes[1]['y']<boxes[2]['y'],boxes
        dimensions.append({'viewport':width,'document':doc,'panels':boxes})
        page.screenshot(path=str(OUT/f'library-{width}.png'),full_page=True)
        page.get_by_role('tab',name='Create',exact=True).click()
        expect(page.get_by_role('button',name='Generate Song',exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth+1')
        page.get_by_role('tab',name='Library',exact=True).click()
    assert not errors,errors
    (OUT/'browser-results.json').write_text(json.dumps({'selection':results,'dimensions':dimensions,'page_errors':errors,'library_checksum_unchanged':True},indent=2))
    browser.close()
assert hashlib.sha256(library.read_bytes()).hexdigest()==before
print('PASS: three native song selections, repeat click, exact search mapping, cover/lyrics/audio HTTP200; Create tab; theme persistence; desktop columns and mobile stacking/no horizontal overflow; no page errors; saved library unchanged.')
