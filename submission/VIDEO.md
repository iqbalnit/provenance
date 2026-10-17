# Demo video: 3:00 script and shot list

The form allows up to 3 minutes and the rules say 3 to 4, so **3:00 or just under** satisfies both.

## Make the video with one command (recommended)

`submission/video/make_video.py` drives the app in a headless browser, takes screenshots at the right moments,
speaks the narration and assembles a 1080p MP4 (about 2:45) with subtitles. There is no waiting and no cursor in
the video, and the narration is written from what the run actually did (which draft was rejected, what the gate
decided), so it cannot describe something the screen does not show. The words are in
`submission/video/script.py`, one beat per shot.

**Once:**
```bash
cd ~/Project_Provenance && git pull
uv run --with playwright playwright install chromium
```

**Optional, for the real-alert segment** (otherwise the agent segment uses the deployed demo alert and says so):
```bash
uv run python -m provenance.data.ofac fetch --live --live-as-of <latest date on OFAC's Recent Actions page> --upload
# set PROVENANCE_OFAC_LIVE_URI in .env to the printed gs:// path, then:
set -a; source .env; set +a
PROVENANCE_DATA=gcp make dev-gemini  # leave running in a second terminal
```

**Build** (8–10 minutes; most of it is Gemini running four cases):
```bash
uv run --with playwright --with imageio-ffmpeg python submission/video/make_video.py \
    --app https://ai-builder-cup-2579.web.app --real http://localhost:8080
```
Drop `--real …` if you skipped the step above. Output in `artifacts/video/`: `provenance.mp4`, `provenance.srt`,
`narration.txt` and every screenshot in `shots/`. Look through `shots/` before uploading.

**Options:**
- `--voice Daniel` (any name from `say -v '?'`; download a Premium or Enhanced voice in System Settings →
  Accessibility → Spoken Content for a more natural sound), `--rate 160` for words per minute. It stops if the video
  would run over 3:00.
- **Kokoro neural voice** (open source, more natural than `say`): download `kokoro-v1.0.onnx` and
  `voices-v1.0.bin` from the `model-files-v1.0` release of github.com/thewh1teagle/kokoro-onnx into a folder,
  add `--with kokoro-onnx --with soundfile` to `uv run`, and pass `--kokoro <folder> --voice af_heart`.
- **Your own voice** (recommended if you have 15 minutes): record each line of `artifacts/video/narration.txt` as
  `submission/video/voice/<beat id>.m4a`, for example `voice/01-problem.m4a`, using QuickTime → New Audio Recording.
  Then `… make_video.py --reuse-shots` re-assembles with your recordings without re-running the app. Beats you have
  not recorded keep the synthetic voice.
- `--real-case <case id>` reuses a finished real case instead of running a new one; `--probe` always demonstrates
  the verifier with the probe.

## Recording by hand (alternative)

Use the beats in `submission/video/script.py` (or `artifacts/video/narration.txt` after one run) as the script.

### What runs where

| Beat | Screen | Data |
|---|---|---|
| Real hero on Gemini | Local console: `PROVENANCE_DATA=gcp make dev-gemini`, then http://localhost:8080 | Real SAML-D alert, real OFAC lists |
| The reversal | The deployed console, https://ai-builder-cup-2579.web.app | Labelled demo bundle (fictional customer) |
| Eval table | `/eval.html` on either | BigQuery `eval_results` |

**Before recording:**
- Run the real hero once and keep that case open, so the drafts history shows a real rejection. Re-run until
  draft 1 is rejected for a genuine reason; Gemini often writes an uncited judgment sentence on this alert.
  If it never does, use **Demo: add an uncited sentence** and say that we added the sentence.
- Deploy with `MIN=1` first, then open the deployed console once so it is warm; otherwise the first load shows
  a "server can take up to 30 seconds" note while Cloud Run starts.
- Browser at 1280×800 or larger, zoom 110%, notifications off, bookmarks bar hidden.

### Recording and upload

For the one-command video, skip to step 4 and also upload `provenance.srt` under Subtitles.

1. **Record:** QuickTime → File → New Screen Recording (or Loom/OBS), 1080p, microphone on. Record each beat
   separately; it is easier to retake one than the whole thing.
2. **Edit:** trim pauses, cut the Gemini wait between Run and the result (say "this takes about a minute on real
   data" once, then cut). iMovie or CapCut is enough. Export 1080p.
3. **Check:** total length ≤ 3:00, audio level steady, no personal email, tabs or notifications visible.
4. **Upload:** YouTube → Create → Upload video → Visibility **Unlisted**. Title: "Provenance: AML triage that
   cannot say what it cannot cite (AI Builder Cup 2026)".
5. **Test:** open the link in a private window, logged out, and play it to the end.
6. **Use the link** in the form, and rebuild the deck with `--video <link>` so slide 13 carries it.
