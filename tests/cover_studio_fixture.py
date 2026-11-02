"""Isolated browser fixture: deterministic endpoint doubles, never touches saved songs."""
import sys, json, time, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from jukebox import config
scratch=Path(sys.argv[1])
config.ROOT=scratch
config.LIBRARY_FILE=scratch/'library.json'
config.COVER_DIR=scratch/'covers'
config.COVER_DIR.mkdir(exist_ok=True)
from jukebox.library import SongLibrary
from jukebox import service
lib=SongLibrary()
for i in range(2):
    cover=config.COVER_DIR/f'original-{i}.png'
    from PIL import Image
    Image.new('RGB', (160, 160), '#344268').save(cover)
    import wave
    with wave.open(str(scratch / f'audio-{i}.wav'), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x00\x00' * 8000 * 30)
    lib.add(title=f'Studio track {i+1}',style='Rock',mood='Melancholic',duration_sec=30,
            instrumental=False,theme=f'Hope after storm {i+1}',lyrics='Rain falls but hope remains',
            cover_path=str(cover.relative_to(scratch)),audio_path=f'audio-{i}.wav')

def brief(song, **kwargs):
    return f"A single seedling on wet asphalt. {kwargs['user_description']} {kwargs['artistic_style']}. Palette: {kwargs['color_palette']}. No lettering."

def generate(song, *, custom_prompt=None):
    assert isinstance(custom_prompt, str)
    with (scratch/'calls.jsonl').open('a') as out:
        out.write(json.dumps({'song_id':song.id,'prompt':custom_prompt})+'\n')
    if 'FAIL_REQUEST' in custom_prompt:
        raise RuntimeError('Injected endpoint failure for recovery test')
    if 'SLOW_REQUEST' in custom_prompt:
        time.sleep(4)
    dest=config.COVER_DIR/f'candidate-{time.time_ns()}.png'
    from PIL import Image
    Image.new('RGB', (160, 160), '#8556ff').save(dest)
    return dest,custom_prompt
service.cover_prompt_for=brief
service.generate_cover=generate
import app
app.build_app().queue(default_concurrency_limit=8).launch(server_name='127.0.0.1',server_port=7863,
    allowed_paths=[str(scratch)],css=app.CUSTOM_CSS,head='<script>'+app._JUKEBOX_JS+'</script>')
