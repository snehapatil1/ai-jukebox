"""Polish acceptance tests. Deliberately does not operate or test DJ controls."""
from pathlib import Path
import json, re, time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/library-layout'
for _ in range(60):
    try: urlopen('http://127.0.0.1:7860',timeout=1).close();break
    except OSError: time.sleep(.5)

def luminance(rgb):
    values=[v/255 for v in rgb[:3]]
    return sum(weight*(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4)
               for weight,v in zip((.2126,.7152,.0722),values))
def contrast(a,b):
    a,b=sorted((luminance(a),luminance(b)))
    return (b+.05)/(a+.05)
def colors(locator):
    return locator.evaluate('(e)=>({fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor})')
def rgb(color):return [float(x) for x in re.findall(r'[\d.]+',color)]

with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':900})
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://127.0.0.1:7860')
    media=page.locator('#nowAudio audio[src]').last
    expect(media).to_have_attribute('src',re.compile('.+'),timeout=45000)
    page.wait_for_timeout(1500)
    assert page.locator('#playBtn').count()==0
    native=page.locator('#nowAudio')
    play=native.get_by_role('button',name='Play',exact=True)
    expect(play).to_be_visible()
    play.click();page.wait_for_timeout(900)
    assert media.evaluate('a=>a.currentTime')>0
    native.get_by_role('button',name='Pause',exact=True).click()
    expect(native.get_by_role('button',name='Play',exact=True)).to_be_visible()
    previous=media.evaluate('a=>a.currentTime')
    native.get_by_role('button',name='Play',exact=True).click();page.wait_for_timeout(500)
    assert media.evaluate('a=>a.currentTime')>=previous
    native.get_by_role('button',name='Pause',exact=True).click()
    print('PASS: single native play/pause resumes without resetting; controls track actual playback')
    results=[]
    for mode in ('dark','light'):
        expect(page.locator('html')).to_have_attribute('data-theme',mode)
        for width in (1440,1024,768,390):
            page.set_viewport_size({'width':width,'height':900})
            page.wait_for_timeout(700)
            assert page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth+1')
            audio_box=native.bounding_box()
            panel=page.locator('#playerPanel').bounding_box()
            assert audio_box['x']+audio_box['width']<=panel['x']+panel['width']+1
            scroll=native.locator('[part="scroll"]')
            expect(scroll).to_have_count(1)
            size=scroll.evaluate('(e)=>({client:e.clientWidth,scroll:e.scrollWidth})')
            assert size['scroll']<=size['client']+1,(width,size)
            wrapper=native.locator('[part="wrapper"]')
            box=wrapper.bounding_box()
            canvases=native.locator('[part="canvases"] canvas').evaluate_all('(es)=>es.map(e=>e.getBoundingClientRect().toJSON())')
            assert max(c['right'] for c in canvases)<=box['x']+box['width']+2
            assert max(c['right'] for c in canvases)>=box['x']+box['width']-3
            for label_id,image_id in [('currentCoverLabel','currentCoverPreview'),('newCoverLabel','newCoverPreview')]:
                label=page.locator('#'+label_id).bounding_box();image=page.locator('#'+image_id).bounding_box()
                assert label['y']+label['height']<=image['y']+1
                assert page.locator('#'+image_id+' .icon-button').count()==0
            if width==1440:
                # At normal desktop height, acceptance actions fit without page scrolling.
                page.evaluate('window.scrollTo(0,0)')
                actions=page.locator('#coverActions').bounding_box()
                assert actions['y']+actions['height']<=900,(mode,actions)
                assert page.locator('#queuePanel').bounding_box()['y']<780
            for style in ('Photo','Illustration','Minimal','Abstract'):
                choice=page.locator('#coverStyle label').filter(has_text=style)
                choice.click();expect(choice.locator('input')).to_be_checked()
                expect(choice).to_have_css('border-top-width','2px')
                assert 'radial-gradient' in choice.locator('input').evaluate('(e)=>getComputedStyle(e).backgroundImage')
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(OUT/f'polished-{mode}-{width}.png'),full_page=True)
            results.append({'mode':mode,'width':width,'waveform':size})
        page.set_viewport_size({'width':1440,'height':900})
        page.evaluate('window.scrollTo(0,0)')
        text_fg=page.locator('#coverStyle').evaluate('e=>getComputedStyle(e).getPropertyValue("--aj-text").trim()')
        # Resolve theme tokens to RGB using a temporary inert element.
        palette=page.evaluate('''()=>{let e=document.createElement('span');e.style.cssText='color:var(--aj-text);background:var(--aj-panel)';document.querySelector('#coverArtStudio').appendChild(e);let r={fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor};e.remove();return r}''')
        normal=contrast(rgb(palette['fg']),rgb(palette['bg']))
        button=page.get_by_role('button',name='Generate new cover',exact=True)
        pair=colors(button);primary=contrast(rgb(pair['fg']),rgb(pair['bg']))
        assert normal>=4.5 and primary>=4.5,(mode,normal,primary)
        print(f'PASS {mode}: responsive fit, selected radios, labels above toolbar-free previews; text contrast {normal:.2f}:1 / primary {primary:.2f}:1')
        if mode=='dark':page.locator('#themeToggle').click()
    # Verify fitting did not crop the timeline: click 75% across maps to 75% of the audio.
    wrapper=native.locator('[part="wrapper"]');box=wrapper.bounding_box()
    wrapper.click(position={'x':box['width']*.75,'y':20})
    page.wait_for_timeout(300)
    current,duration=media.evaluate('a=>[a.currentTime,a.duration]')
    assert abs(current/duration-.75)<.08,(current,duration)
    assert not errors,errors
    (OUT/'polish-browser-results.json').write_text(json.dumps({'viewports':results,'page_errors':errors,'seek_fraction':current/duration},indent=2))
    browser.close()
print('PASS: full waveform seeking, no horizontal overflow; DJ controls were not touched or tested.')
