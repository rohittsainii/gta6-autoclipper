# GTA 6 auto-clipper

Runs entirely on GitHub's computers + Claude. Nothing runs on your laptop.

```
every hour  ──>  Find moments (GitHub Actions)
                 new VODs of the campaign streamers → viewer clips + loudness + "most replayed"
                 → top moments transcribed (ElevenLabs, faster-whisper fallback) → candidates/*.json
every 2 h   ──>  Claude (scheduled task) reads candidates, picks the best 2–5, writes hook + caption → picks/*.json
on push     ──>  Render clips (GitHub Actions) → 9:16 mp4 with hook, #ad, word-by-word captions
                 → published as a GitHub Release with POST.md (captions ready to paste)
```

## One-time setup
1. **Settings → Secrets and variables → Actions → New repository secret**
   - `ELEVENLABS_API_KEY` = your ElevenLabs API key (never paste it in chat).
   - `YT_COOKIES` (optional) = only if YouTube blocks downloads; a cookies.txt export from a throwaway Google account.
2. Free minutes: a private repo gets 2,000 Actions minutes/month. Four marathon streamers can use more than that.
   Making the repo public gives unlimited free minutes (secrets stay secret).

## Day-to-day
- New clips: **Releases** on this repo (GitHub app on your phone works). Each release has the mp4s and POST.md.
- Add/turn on a campaign: edit `config/campaigns.json` (add the streamer's Twitch handle or YouTube URL, set `enabled: true`).
- Facecam split layout: set `facecam` to `[x, y, w, h]` (fractions of the frame) for that streamer.
- Problems: `state/last_run.md` shows the last run's log.
