# How Claude picks clips (read on every scheduled run)

Channels: `en` = **GTA 6 Clips** (English creators), `hi` = Indian channel (later). Every finished clip is posted
automatically to that channel's YouTube, Instagram and Facebook, with no human review, so the bar is high.

For every `candidates/*.json` with `"status": "new"`:

1. Find the creator in `config/campaigns.json` → `creators` (the candidate's `campaign` field is the creator id).
   **If `permission` is not `true`, do not pick anything**: set the candidate's status to `"no_permission"` and move on.
   For creators with `"permission_mode": "per_video"` (found by the scout), also read the candidate's `permission_quote`:
   it must clearly let anyone clip/re-use the content (e.g. "feel free to clip, just credit me"). If it is ambiguous, limited
   (e.g. "members only", "for my clip channel only", "ask first") or not really permission, set status `"no_permission"`,
   set that creator's `permission` to `false` in config with a short reason in `permission_proof`, and move on.
2. Read each moment's `text`, `signals` and `score`, and **look at its `frames`** (3 small stills: start, peak, end; open them with your image-reading tool). Hooks, titles and commentary must match what is actually on screen. If a moment has no frames, only say what the transcript makes certain. Pick the **1–4 best** per file (quality over quantity). Skip a moment if:
   - it needs context a new viewer won't have, it's dead air or menu/loading talk, or nothing actually happens
   - it's a pure cutscene (Rockstar takes those down), a story spoiler, leaked content, or drama/harassment bait
   - it's another person's stream or music (copyright risk), or the creator isn't the focus
   - it contains slurs, sexual content or anything that would get the channel limited
   Prefer: first reactions, "NO WAY" discoveries, funny fails, chaos, big laughs, hot takes. `viewer clip` signals are strong evidence.
3. Exact `start`/`end` from the word timestamps (absolute seconds into the VOD): **15–45 s**. Start 0.5 s before the setup, end right after the payoff/reaction, never mid-sentence.
4. Write, for each clip:
   - `hook`: on-screen title, max 7 words, no emoji, true to the clip.
   - `title`: YouTube title, max 90 chars, names the creator and GTA 6, curiosity without lying (e.g. "Lacy tried to pet a gator in GTA 6…").
   - `caption`: 1–2 lines for Instagram/Facebook/YouTube description, may use 1 emoji. The renderer adds the creator credit and hashtags. **No #ad** (this is not a paid campaign).
   - `voice_intro`: **our commentary**, read by the channel voice over the first seconds (stream audio is lowered). Max ~14 words. Set up what's about to happen in our own words; never just repeat the hook.
   - `voice_outro`: **our take**, read over the frozen last frame. Max ~22 words. A real opinion, insight, comparison or joke about what just happened (why it's funny, what it says about GTA 6, what the creator should have done). This commentary is what makes the channel original, so make it specific to the clip.
   - `sfx`: 1–3 sound-effect cues at the exact funny/shocking beats, as `{"t": <absolute VOD seconds>, "type": "..."}`.
     Types: `boom` (the punchline / biggest reaction; also flashes the screen; max one per clip), `scratch` (a fail or things going wrong),
     `ding` (a discovery / "wait, what?"), `gasp` (something shocking), `pop` (small beat). A whoosh at the start and a riser into
     the outro are added automatically. Fewer, well-timed sounds beat many: never cover the streamer's punchline words.
   Never reuse the same intro/outro wording across clips (YouTube penalises repetitive templates). No made-up facts about the game: if unsure, give an opinion instead of a claim.
5. Language: `en` creators → English everywhere, no `words`. `hi` creators → commentary in natural Hinglish (Hindi in Roman letters), plus `words`: the transcript words with the same timings rewritten in Hinglish.
6. Save `picks/<candidate-file-name>.json`:
   ```json
   {"candidate_file": "candidates/<name>.json",
    "clips": [{"moment_id": "m3", "start": 4521.3, "end": 4549.0, "hook": "...", "title": "...",
               "caption": "...", "voice_intro": "...", "voice_outro": "...",
               "sfx": [{"t": 4530.2, "type": "boom"}]}]}
   ```
   and set the candidate's `"status": "picked"` (or `"skipped"` if nothing is good enough).
   Then delete that candidate's stills (`git rm -r -q candidates/frames/<candidate-file-name-without-.json>`) to keep the repo small.
7. Commit and push. The push starts the render workflow; each finished clip becomes its own GitHub Release, which Zapier posts.

Then read `state/find_log.md` and `state/render_log.md` and report any ERROR lines.
