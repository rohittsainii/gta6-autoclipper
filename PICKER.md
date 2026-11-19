# How Claude picks clips (read on every scheduled run)

For every `candidates/*.json` with `"status": "new"`:

1. Read the campaign in `config/campaigns.json` (its `rules` and `caption_must_include`).
2. Read each moment's `text`, `signals` and `score`. Pick the **2–5 best** per file. Skip a moment if:
   - it needs context a new viewer won't have, it's dead air or menu/loading talk, or nothing actually happens
   - it's a pure cutscene (Rockstar takes those down), a leak/spoiler of the ending, or drama bait
   - the campaign's streamer isn't the focus
   Prefer: first reactions, "NO WAY" discoveries, funny fails, chaos, big laughs, hot takes. `viewer clip` signals are strong evidence.
3. For each pick choose exact `start`/`end` inside the moment using word timestamps (absolute seconds into the VOD):
   - 15–45 s long. Start 0.5 s before the strongest line or action, so second one is the payoff or the setup to it. End right after the punchline/reaction, not mid-sentence.
4. Write a `hook` (max 7 words, CAPS-friendly, **no emoji**, no clickbait that the clip doesn't deliver).
5. Write a `caption` for posting: 1 line + hashtags. Must contain `caption_must_include`, plus `#GTA6 #GTAVI`, plus `#ad` at the start for disclosure.
6. Language: `en` → leave `words` out (the transcript is used). `hi` → add `words`: the same timings, each word rewritten in Hinglish (Hindi in Roman letters, e.g. "bhai ye kya hua").
7. Save `picks/<candidate-file-name>.json`:
   ```json
   {"candidate_file": "candidates/<name>.json",
    "clips": [{"moment_id": "m3", "start": 4521.3, "end": 4549.0, "hook": "...", "caption": "#ad ..."}]}
   ```
   and set the candidate's `"status": "picked"` (or `"skipped"` if nothing is good enough).
8. Commit and push. The push starts the render workflow, which publishes the videos as a GitHub Release with `POST.md`.

Then read `state/find_log.md` and `state/render_log.md` and report any ERROR lines.
