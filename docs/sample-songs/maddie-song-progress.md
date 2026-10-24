# Sample Song Development — Maddie Branch

**Song:** Untitled indie/alternative-rock sample  
**Branch:** `maddie` (tracking `origin/maddie`, identical to `master` @ `af87f63`)  
**Last updated:** 2026-10-24

---

## Status

- Song remains in development; no audio version is approved as final.
- Qwen on port 9001 generated the draft lyrics and three alternative Verse 1 options.
- ACE-Step on port 9007 generated three 105-second tasks, plus the second returned variants for V2 and V3.
- No cover art has been generated.
- All audio remains private and gitignored.

---

## Creative Direction

### Genre & Mood

Dark, uneasy indie/alternative-rock foundation with a prominent melodic bass line. The overall aesthetic is melancholic and restrained — never bright, warm, or country-influenced. Emotional arc moves through: fragile intimacy → unsettling tension → quiet defiance → unresolved ending.

### Lyrical Theme

Human connection and lived memory — a live-music setting where strangers share something real but unnamed. Focus on physical proximity, shared words, and collective breath rather than romantic narrative.

### Vocal Approach

Single consistent masculine lead vocal throughout — low tenor or light baritone. Intimate, dry, close-miked delivery with minimal vibrato. Subtle natural grit allowed. Tasteful layered backing vocals permitted in the final chorus only (on "We still do"). No crowd shouting, no robotic replacement singer, no theatrical or country-inflected pronunciation.

### Structure & Length

Approximately 105 seconds. Intro → Verse 1 → Chorus → Verse 2 → Bridge → Break → Final Chorus → Unresolved outro. No extended silences; texture sustains through the break.

### Constraints

- Do not name, imitate, or evoke any specific artist, song, or album.
- Avoid technical vocabulary and AI references entirely.
- End unresolved and uneasy, not triumphant.

---

## Current Full Lyric Draft (Version One)

*Draft — awaiting final lyrical review before audio synthesis.*

Wood floor shivers under my shoes  
Stage lights bleed through the haze  
You step up, eyes closed, breath caught in your throat  
A moment before the noise takes hold  
I feel the tremor in the rafters above  
Your voice cuts close enough to touch  
Strangers' voices sing the same words  
The room begins to breathe in time  

Do you miss anyone when you sing?  
I still do  

But the voice is too clean, too sharp, too right  
No scar tissue, no history behind the mic  
It glides without a trace of pain  
A perfect face with nothing underneath  

It pulls you in with quiet grace  
A shadow cast by empty space  
Seductive sound that feels so true  
Yet carries none of what it sings about  
Beautiful void with dangerous charm  
Longing for a ghost's arm  

Do you miss anyone when you sing?  
We still do  
(Hushed, layered harmonies)  
We still do  

Do you miss...  
Anyone...

---

## Latest Verse 1 Alternatives (Qwen Output — Port 9001)

*Draft — meter analysis shows all lines exceed the 7–8 syllable target. Not approved as replacements.*

### [Verse 1A]

The bass shakes dust from the rafters high  
I feel the floor tilt under my feet  
Spotlights cut through the thick humid air  
You lean close, your breath hits my skin  
Strangers in shadows hum every word  
We are not alone in this dark room  
For a moment we breathe as one mass  
Then silence falls heavy on the stage  

### [Verse 1B]

Neon bleeds into the crowded space  
My boots slide on the vibrating wood  
Your voice cracks open inside the noise  
I hear the wet catch of your throat  
Faces I do not know sing along  
They hold the lyrics like shared secrets  
The whole building inhales with the beat  
And holds it there until you stop  

### [Verse 1C]

Shadows pool around the microphone stand  
The ground rolls like water beneath me  
Cold light washes over your tired face  
I smell the salt on your exhale  
A dozen voices rise to meet yours  
Knowing the lines better than you do  
We pulse together in the gloom tight  
Until the music lets us go again  

---

## Listening Results

| Version | Outcome | Details |
|---------|---------|---------|
| **V1 first variant** | Rejected | Too bright, warm, country-influenced, conventionally rock-oriented. Short intro. Artificial-sounding vocal. Break resembled a false ending. |
| **V2 first variant** | **Best current reference, not approved** | Darker G-minor direction improved mood and first-half vocal. However, phrasing still sounds recited, musical flow lacks consistency, and the break needs improvement. Used as musical reference for subsequent revisions. |
| **V2 second variant** | Rejected | First half remained poor. Contained an especially unpleasant and out-of-tune chord. |
| **V3 first variant** | Not approved | Slightly improved lower guitar and darker direction overall. But vocal melody was not noticeably more coherent than V2; first-half voice was worse than V2. |
| **V3 second variant** | Not approved | Slightly better first half than V3 first variant, but still sounded recited. Guitar was uninteresting. Lyric inflection and melody remained inconsistent. |

---

## Current Findings

1. **Verse 1 phrasing is the primary issue.** The original Verse 1 has uneven phrasing and likely contributes to ACE-Step's recitation-like delivery across all versions. Meter-focused refinement is needed before another audio generation pass.

2. **Three meter-focused Verse 1 alternatives were generated by Qwen**, but automated syllable counting showed substantial overcounting across all lines. Candidate B appears closest to a consistent 8–9 syllable range per line.

3. **Specific lines flagged for reconsideration:** "I hear the wet catch of your throat" and the use of "boots" in Candidate B feel incongruous with the established mood. These should be revised if Candidate B becomes the basis for further iteration.

4. **Instrumental-first workflow limitations.** The class endpoint does not reliably support generating an instrumental arrangement first and layering vocals afterward. This capability remains unverified. Prompt engineering via unified prompt + lyrics input is the most practical approach.

5. **Musical reference locked.** Next session should start from the V2 first variant as the musical reference point. Refine Verse 1's meter and regenerate audio rather than changing the entire arrangement again.

---

## Local Audio Previews (Gitignored)

The following files exist in the local `data/` directory. They are excluded from Git tracking and will **not** appear in the committed repository.

| Filename | Size | Notes |
|----------|------|-------|
| `private_preview_v1_20261024_191716.mp3` | 1.6 MB | V1 first variant — rejected |
| `private_preview_v2_20261024_192607.mp3` | 1.6 MB | V2 first variant — best current reference |
| `private_preview_v2_variant2_20261024_201708.mp3` | 1.6 MB | V2 second variant — retrieved and downloaded |
| `private_preview_v3_20261024_193155.mp3` | 1.6 MB | V3 first variant — not approved |
| `private_preview_v3_variant2_20261024_201708.mp3` | 1.6 MB | V3 second variant — retrieved and downloaded |

Each MP3 has a companion `.metadata.json` file (V1 and V2-V3 originals have them; variant2 files are pending).
