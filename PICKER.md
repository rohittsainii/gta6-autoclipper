# How Claude picks clips (read on every scheduled run)

Channels: `en` = **GTA 6 Clips** (English creators), `hi` = Indian channel (later). Every finished clip is posted
automatically (12:30 PM–5 PM IST) to the platforms its campaign allows, with no human review, so the bar is high.
Each creator in `config/campaigns.json` is a **Whop campaign Rohit joined**; its `rules` are the campaign's rules and
breaking one means the clip earns nothing or the account gets banned. Read `rules` before picking.

For every `candidates/*.json` with `"status": "new"`:

1. Find the creator in `config/campaigns.json` → `creators` (the candidate's `campaign` field is the creator id).
   **If `permission` is not `true`, do not pick anything**: set the candidate's status to `"no_permission"` and move on.
   **If `hold` is `true`** (rules not read yet, or a required overlay file is missing), don't pick either: set status `"held"` and move on.
2. Read each moment's `text`, `signals` and `score`, and **look at its `frames`** (3 small stills: start, peak, end; open them with your image-reading tool). Hooks, titles and commentary must match what is actually on screen. If a moment has no frames, only say what the transcript makes certain. Pick the **1–4 best** per file (quality over quantity). Skip a moment if:
   - it needs context a new viewer won't have, it's dead air or menu/loading talk, or nothing actually happens
   - it's a pure cutscene (Rockstar takes those down), a story spoiler, leaked content, or drama/harassment bait
   - it's another person's stream or music (copyright risk), or **the campaign creator isn't the main focus** (Lacy, Kai Cenat and Dylan Page reject clips where they aren't; for Dylan they must be on screen the whole clip, not just the start)
   - it contains slurs, sexual content or anything that would get the channel limited
   Prefer: first reactions, "NO WAY" discoveries, funny fails, chaos, big laughs, hot takes. `viewer clip` signals are strong evidence.
3. Exact `start`/`end` from the word timestamps (absolute seconds into the VOD): **aim for 15–30 s, hard max 40 s** (viral streamer Shorts in our niche have a median of 22 s; longer clips lose viewers). Cut every second of setup that isn't needed: the first 1–2 s must already show the situation or the reaction (viewers decide to swipe in under 2 s). Start at most 0.5 s before the key line, end right on the biggest laugh/reaction, never mid-sentence. Prefer endings that loop back naturally into the start (rewatches count heavily).
4. Write, for each clip:
   - `hook`: on-screen title, max 7 words, no emoji, true to the clip. It is on screen from frame 1 (most first views are sound-off), so it must make sense without audio.
   - `title`: the formula that works in this niche: **"[Creator] [did a specific thing]" + 1–2 emoji at the end**, about 35–55 chars, no hashtags in the title (e.g. "Lacy Tried To Pet A Gator In GTA 6 😭🐊", "Kai Cenat Got Robbed By An NPC 💀"). Creator name first, Title Case, concrete detail (an amount, an object, a person) beats vague words like "crazy" or "insane". Best emoji: 😭 💀 😂, plus one object emoji that fits. Must be true to the clip.
   - `caption`: 1 short line for Instagram/Facebook/TikTok/YouTube description, ideally a question that invites comments ("Would you have run? 😭"). The renderer adds the credit line and 3–5 hashtags. The renderer adds the campaign's credit line and required hashtags. **No URLs or @links in the caption** (KreekCraft's campaign bans links; keep it uniform). No #ad.
   - **If the creator's `voice` is `false`** (Lacy, Kai Cenat, Brett, Dylan Page: their campaigns ban AI-generated content; Dylan also bans "fabricated reactions", so never use `gasp` for him), leave out `voice_intro` and `voice_outro` entirely; the clip runs on the stream audio alone, so pick moments that land without explanation.
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
