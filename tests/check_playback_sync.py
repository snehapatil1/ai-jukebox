"""The consolidated native controls must reflect actual playback."""
import re
from playwright.sync_api import sync_playwright,expect
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page()
    page.goto('http://127.0.0.1:7860')
    audio=page.locator('#nowAudio audio[src]').last
    expect(audio).to_have_attribute('src',re.compile('.+'),timeout=45000)
    page.wait_for_timeout(1500)
    assert page.locator('#playBtn').count()==0,'Duplicate play control must not reappear'
    player=page.locator('#nowAudio')
    player.get_by_role('button',name='Play',exact=True).click()
    page.wait_for_timeout(800)
    assert audio.evaluate('a=>a.currentTime')>0
    player.get_by_role('button',name='Pause',exact=True).click()
    before=audio.evaluate('a=>a.currentTime')
    assert audio.evaluate('a=>a.paused')
    player.get_by_role('button',name='Play',exact=True).click()
    page.wait_for_timeout(500)
    assert not audio.evaluate('a=>a.paused')
    assert audio.evaluate('a=>a.currentTime')>=before
    player.get_by_role('button',name='Pause',exact=True).click()
    browser.close()
print('PASS: one native Play/Pause control; resume continues instead of restarting.')
