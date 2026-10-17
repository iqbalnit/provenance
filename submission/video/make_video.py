"""Build the demo video: capture the running app, speak the narration, assemble a 1080p MP4 with subtitles.

    uv run --with playwright --with imageio-ffmpeg python submission/video/make_video.py \
        --app https://ai-builder-cup-2579.web.app [--real http://localhost:8080] [--voice Samantha]

Shots are screenshots of the real console taken at the right moments, so the video has no waiting and no cursor.
Each beat in script.py is spoken separately and its shot is held for exactly that long. Narration that depends on
the run (which draft was rejected, what the gate decided) is written from what the capture saw.

Voice: macOS `say` by default; `espeak-ng` elsewhere (testing only). To use your own voice, record any beat as
submission/video/voice/<beat id>.m4a (or .wav/.aiff/.mp3) and run again with --reuse-shots.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
import wave
from datetime import date
from pathlib import Path

import imageio_ffmpeg
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
import script  # noqa: E402

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
NUMBERS = json.loads((ROOT / "submission/deck/numbers.json").read_text())
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS = 1920, 1080, 30
BG = "0xF6F7F9"
GAP_S = 0.35          # breath after each beat
LIMIT_S = 180.0
REAL_HERO = "alt_95bf5f09d5"
VIEW = {"width": 1280, "height": 720}   # rendered at 2x, so console text is large at 1080p


# ---------- capture ----------

async def shot(page, sel: str, out: Path, max_h: float | None = None, around: str | None = None) -> None:
    """Screenshot an element; tall elements are clipped to a 16:9-ish window (around a child, if given)."""
    page_box = "(e) => { const r = e.getBoundingClientRect(); return {x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height}; }"
    box = await page.locator(sel).first.evaluate(page_box)
    if not box["height"]:
        raise RuntimeError(f"{sel} is not visible")
    cap = max_h or max(box["width"] * 9 / 16, 660)
    y = box["y"]
    if around and await page.locator(around).count():
        a = await page.locator(around).first.evaluate(page_box)
        y = max(box["y"], min(a["y"] + a["height"] / 2 - cap / 2, box["y"] + box["height"] - cap))
    h = min(box["height"] - (y - box["y"]), cap)
    pad = 8
    await page.screenshot(path=str(out), full_page=True, clip={
        "x": max(0, box["x"] - pad), "y": max(0, y - pad), "width": box["width"] + 2 * pad, "height": h + 2 * pad})


async def viewport(page, out: Path) -> None:
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(250)
    await page.screenshot(path=str(out))


CARD_CSS = """
body { margin: 0; width: 1600px; height: 900px; display: grid; place-items: center; background: #F6F7F9;
  font-family: -apple-system, "Segoe UI", system-ui, sans-serif; color: #101826; }
.wrap { width: 1300px; } .kick { font-size: 22px; letter-spacing: .12em; text-transform: uppercase; color: #5B6474; }
h1 { font-size: 64px; line-height: 1.12; margin: 18px 0 36px; font-weight: 700; }
.row { display: flex; gap: 28px; } .stat { flex: 1; background: #fff; border: 1px solid #E3E6EB; border-radius: 18px;
  padding: 30px 32px; } .stat .v { font-size: 72px; font-weight: 750; } .stat .k { font-size: 24px; color: #5B6474; margin-top: 6px; }
.bad .v { color: #B42318; } .ok .v { color: #0F7B4B; } .amber .v { color: #D97706; }
.foot { margin-top: 30px; font-size: 22px; color: #5B6474; }
.chips { display: flex; flex-wrap: wrap; gap: 14px; } .chip { background: #fff; border: 1px solid #E3E6EB; border-radius: 999px;
  padding: 12px 24px; font-size: 26px; font-weight: 600; }
"""


def cards() -> dict[str, str]:
    n, rr, ho = NUMBERS["rule_engine"], NUMBERS["real_reversal"], NUMBERS["held_out"]
    stat = lambda v, k, tone="": f'<div class="stat {tone}"><div class="v">{v}</div><div class="k">{k}</div></div>'  # noqa: E731
    return {
        "problem": f"""<div class="kick">The problem</div><h1>Banks clear AML alerts by hand.<br>Almost all are false alarms.</h1>
            <div class="row">{stat(f"{n['transactions'] / 1e6:.1f}M", "transactions (SAML-D)")}
            {stat(f"{n['alerts']:,}", "alerts from the rule engine", "amber")}
            {stat(f"{n['fp_rate'] * 100:.0f}%", "of alerts are false positives", "bad")}</div>
            <div class="foot">Every one is cleared by an analyst, about {NUMBERS['analyst_minutes_per_alert']} minutes each.</div>""",
        "clock": f"""<div class="kick">Measured on {rr['n']} real alerts · sanctions list 30 months old</div>
            <h1>The clock decides whether<br>stale evidence closes cases</h1>
            <div class="row">{stat(rr['naive_auto_closed'], "auto-close decisions with a fetch-date clock", "bad")}
            {stat(rr['publisher_auto_closed'], "with Provenance's publisher-date clock", "ok")}
            {stat(f"{rr['staleness_failed']} of {rr['n']}", "cases flagged as stale evidence", "amber")}</div>""",
        "heldout": f"""<div class="kick">Held-out test · alerts never used for tuning</div><h1>On {ho['n']} unseen alerts</h1>
            <div class="row">{stat(f"{ho['auto_close_rate'] * 100:.0f}%", "cleared automatically, every sentence cited", "ok")}
            {stat(f"{ho['suspicious_auto_closed']} of {ho['suspicious']}", "suspicious alerts closed", "ok")}
            {stat(ho['escalated_by_corridor_rule'], "high-risk corridor alerts kept for an analyst", "amber")}</div>""",
        "close": """<div class="kick">Provenance · AI Builder Cup 2026</div>
            <h1>AML triage that cannot say<br>what it cannot cite, and knows<br>how old its evidence is</h1>
            <div class="chips"><span class="chip">Gemini on Vertex AI</span><span class="chip">Agent Development Kit</span>
            <span class="chip">Cloud Run</span><span class="chip">Firebase Hosting</span><span class="chip">Firestore</span>
            <span class="chip">BigQuery</span><span class="chip">Cloud Storage</span></div>
            <div class="foot">ai-builder-cup-2579.web.app</div>""",
    }


async def wait_ready(page, timeout_s: int = 120) -> dict:
    await page.wait_for_function("document.getElementById('run') && !document.getElementById('run').disabled",
                                 timeout=timeout_s * 1000)
    return await page.evaluate("meta")


async def wait_case(page, case_id: str, timeout_s: int) -> dict:
    for _ in range(timeout_s):
        c = await page.evaluate("id => fetch('/api/cases/' + id).then(r => r.json())", case_id)
        if c.get("status") in ("done", "error", "reopened"):
            return c
        await page.wait_for_timeout(1000)
    raise TimeoutError(f"case {case_id} did not finish in {timeout_s}s")


async def settle(page, case_id: str) -> None:
    await page.wait_for_function("id => current === id && document.querySelector('#decision .big')", arg=case_id,
                                 timeout=60000)
    await page.wait_for_timeout(1200)


async def capture_agent(page, base: str, real: bool, case_id: str | None, probe: bool, out: Path, log) -> dict:
    await page.goto(base + "/")
    meta = await wait_ready(page)
    if not case_id:
        ids = [a["alert_id"] for a in meta["alerts"]]
        alert = REAL_HERO if real else next((a for a in ids if "hero" in a), ids[0])
        if alert not in ids:
            raise SystemExit(f"{alert} is not in {base}'s alert list. Is it running with PROVENANCE_DATA=gcp?")
        await page.select_option("#alert", alert)
        await page.click('#snap button[data-v="live"]')
        await page.click('#basis button[data-v="source_as_of"]')
        await page.click("#run")
        await page.wait_for_function("current", timeout=60000)
        case_id = await page.evaluate("current")
        log(f"  running {alert} as {case_id} (Gemini takes 1-3 minutes)…")
    else:
        await page.evaluate("id => show(id)", case_id)
    c = await wait_case(page, case_id, 420)
    if c["status"] == "error":
        raise SystemExit(f"case {case_id} failed: {c.get('error')}")
    await settle(page, case_id)
    rejected = next((a for a in c.get("attempts") or [] if not a.get("passed")), None)
    facts = {"real": real, "case_id": case_id, "decision": c.get("decision"),
             "rejected_uncited": len(rejected.get("failures", [])) if rejected else 0,
             "sanctions_hit": any(x.get("sanctions_or_pep_hit") for x in c.get("claims") or [])}
    await viewport(page, out / "agent-overview.png")
    await shot(page, "#ledgercard", out / "agent-ledger.png")
    if probe or not facts["rejected_uncited"]:
        facts["rejected_uncited"] = 0
        log("  demonstrating the verifier with the probe (draft 1 passed, or --probe)")
        await page.click("#probe")
        await page.wait_for_function("document.querySelector('#probes .probe-card')", timeout=60000)
        await page.wait_for_timeout(800)
        await shot(page, "#probes", out / "agent-drafts.png")
    else:
        await shot(page, "#drafts", out / "agent-drafts.png")
    await shot(page, "#resultgrid > section", out / "agent-gate.png")
    return facts


async def capture_reversal(page, base: str, out: Path, log) -> dict:
    await page.goto(base + "/")
    meta = await wait_ready(page)
    await page.click("#rev")
    log("  reversal: three runs (Gemini takes 1-4 minutes)…")
    await page.wait_for_function(
        "[0,1,2].every(i => { const e = document.getElementById('t' + i); return e && /CLOSE|ESCALATE/.test(e.textContent) })",
        timeout=480000, polling=1000)
    await page.wait_for_timeout(1500)
    outcomes = [await page.inner_text(f"#t{i}") for i in range(3)]
    log(f"  reversal outcomes: {outcomes}")
    if outcomes != ["AUTO-CLOSE", "ESCALATE", "ESCALATE"]:
        log("  WARNING: the reversal did not come out AUTO-CLOSE / ESCALATE / ESCALATE; check the shots before using them")
    await shot(page, "#revcard", out / "rev-tiles.png")
    for i in range(3):
        tile = page.locator("#tiles .tile").nth(i)
        cid = await tile.get_attribute("data-id")
        await tile.click()
        await settle(page, cid)
        await page.evaluate("window.scrollTo(0, 0)")
        if i == 2:
            await shot(page, "#ledgercard", out / f"rev-t{i}.png", around="#ledger .pill.hit")
        else:
            await shot(page, "#resultgrid > section", out / f"rev-t{i}.png")
    as_of = date.fromisoformat(meta["snapshots"]["archived"]["as_of"][:10])
    today = date.today()
    return {"archived_months": (today.year - as_of.year) * 12 + today.month - as_of.month - (today.day < as_of.day),
            "reversal": outcomes}


async def capture_eval(page, base: str, out: Path) -> None:
    await page.goto(base + "/eval.html")
    await page.wait_for_function("document.getElementById('bootmsg').hidden", timeout=120000)
    await page.wait_for_timeout(1500)
    arms = "section.card:has(#arms)"
    await page.evaluate("""() => { for (const tr of document.querySelectorAll('#arms tr'))
        if (tr.querySelector('.arm')?.textContent === 'A1') tr.querySelectorAll('td').forEach((td) => td.style.background = '#FEF3E2'); }""")
    await shot(page, arms, out / "eval-a1.png")
    await page.evaluate("""() => { for (const tr of document.querySelectorAll('#arms tr')) {
        const a = tr.querySelector('.arm')?.textContent;
        tr.querySelectorAll('td').forEach((td) => td.style.background = (a === 'A1' || a === 'A3') ? '#FEF3E2' : ''); } }""")
    await shot(page, arms, out / "eval-arms.png")


async def capture(args, out: Path, log) -> dict:
    async with async_playwright() as p:
        launch = {"executable_path": args.chromium} if args.chromium else {}
        b = await p.chromium.launch(**launch)
        card = await b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        for k, html in cards().items():
            await card.set_content(f"<style>{CARD_CSS}</style><div class='wrap'>{html}</div>")
            await card.screenshot(path=str(out / f"card-{k}.png"))
        page = await b.new_page(viewport=VIEW, device_scale_factor=2)
        log("capturing the evaluation page…")
        await capture_eval(page, args.app, out)
        log("capturing the agent run…")
        facts = await capture_agent(page, args.real or args.app, bool(args.real), args.real_case, args.probe, out, log)
        log("capturing the reversal…")
        facts |= await capture_reversal(page, args.app, out, log)
        await b.close()
    (out / "facts.json").write_text(json.dumps(facts, indent=2))
    return facts


# ---------- voice ----------

def ff(*a: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


def to_wav(src: Path, dst: Path) -> float:
    ff("-i", str(src), "-ac", "1", "-ar", "48000", "-sample_fmt", "s16", str(dst))
    with wave.open(str(dst)) as w:
        return w.getnframes() / w.getframerate()


def speak(beat_id: str, text: str, tmp: Path, voice: str, rate: int) -> Path:
    own = next((p for ext in ("m4a", "wav", "aiff", "mp3") if (p := HERE / "voice" / f"{beat_id}.{ext}").exists()), None)
    if own:
        return own
    if shutil.which("say"):
        raw = tmp / f"{beat_id}.aiff"
        subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(raw), script.spoken(text)], check=True)
    elif shutil.which("espeak-ng"):
        raw = tmp / f"{beat_id}.raw.wav"
        subprocess.run(["espeak-ng", "-v", "en-us", "-s", str(rate), "-w", str(raw), script.spoken(text)], check=True)
    else:
        raise SystemExit("No voice: run on macOS (say), install espeak-ng, or record voice/<beat id>.m4a files.")
    return raw


# ---------- assemble ----------

def srt_time(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def subtitles(beats: list[tuple[str, float, float]]) -> str:
    """One cue per sentence, timed by its share of the beat's characters."""
    cues, n = [], 0
    for text, start, dur in beats:
        parts = [s for s in re.split(r"(?<=[.;?])\s+", text) if s]
        total, t = sum(len(s) for s in parts), start
        for s in parts:
            d = dur * len(s) / total
            n += 1
            cues.append(f"{n}\n{srt_time(t)} --> {srt_time(t + d - 0.05)}\n{s}\n")
            t += d
    return "\n".join(cues)


def clip(img: Path, dur: float, dst: Path) -> None:
    frames = max(1, round(dur * FPS))
    vf = (f"scale={2 * W}:{2 * H}:force_original_aspect_ratio=decrease,"
          f"pad={2 * W}:{2 * H}:(ow-iw)/2:(oh-ih)/2:color={BG},"
          f"zoompan=z='1+0.035*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
          f"fade=t=in:st=0:d=0.25:color={BG},fade=t=out:st={max(0, dur - 0.25):.3f}:d=0.25:color={BG},format=yuv420p")
    ff("-i", str(img), "-vf", vf, "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
       "-r", str(FPS), str(dst))


def assemble(facts: dict, shots: Path, out: Path, voice: str, rate: int, log) -> float:
    tmp = out / "build"
    tmp.mkdir(exist_ok=True)
    timeline, audio, t = [], [], 0.6     # short lead-in before the first word
    silence = tmp / "gap.wav"
    ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", str(GAP_S), "-sample_fmt", "s16", str(silence))
    lead = tmp / "lead.wav"
    ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.6", "-sample_fmt", "s16", str(lead))
    audio.append(lead)
    tail = tmp / "tail.wav"
    ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.6", "-sample_fmt", "s16", str(tail))
    for beat_id, shot_key, text in script.BEATS:
        text = text(facts) if callable(text) else text
        wav = tmp / f"{beat_id}.wav"
        dur = to_wav(speak(beat_id, text, tmp, voice, rate), wav)
        timeline.append((beat_id, shot_key, text, t, dur))
        audio += [wav, silence]
        t += dur + GAP_S
    total = t + 0.6
    audio.append(tail)
    log(f"narration: {total:.1f}s")

    # One clip per beat; the first beat also covers the lead-in, the last one the tail.
    lst = []
    for i, (beat_id, shot_key, _, start, dur) in enumerate(timeline):
        length = dur + GAP_S + (0.6 if i == 0 else 0) + (0.6 if i == len(timeline) - 1 else 0)
        img = shots / f"{shot_key.replace(':', '-')}.png"
        dst = tmp / f"{beat_id}.mp4"
        clip(img, length, dst)
        lst.append(f"file '{dst.name}'")
    (tmp / "clips.txt").write_text("\n".join(lst) + "\n")
    (tmp / "audio.txt").write_text("".join(f"file '{a.resolve()}'\n" for a in audio))
    ff("-f", "concat", "-safe", "0", "-i", str(tmp / "audio.txt"), str(tmp / "narration.wav"))
    srt = out / "provenance.srt"
    srt.write_text(subtitles([(text, start, dur) for _, _, text, start, dur in timeline]))
    (out / "narration.txt").write_text("\n\n".join(f"[{b}] {text}" for b, _, text, _, _ in timeline) + "\n")
    ff("-f", "concat", "-safe", "0", "-i", str(tmp / "clips.txt"), "-i", str(tmp / "narration.wav"), "-i", str(srt),
       "-map", "0:v", "-map", "1:a", "-map", "2:s", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
       "-c:s", "mov_text", "-metadata:s:s:0", "language=eng", "-movflags", "+faststart", "-t", f"{total:.3f}",
       str(out / "provenance.mp4"))
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", default="https://ai-builder-cup-2579.web.app", help="deployed console (reversal, eval)")
    ap.add_argument("--real", help="local real-data console, e.g. http://localhost:8080 (PROVENANCE_DATA=gcp)")
    ap.add_argument("--real-case", help="reuse a finished case on --real (or --app) instead of running a new one")
    ap.add_argument("--probe", action="store_true", help="show the verifier probe even if a real draft was rejected")
    ap.add_argument("--voice", default="Samantha", help="macOS voice (say -v '?' lists them)")
    ap.add_argument("--rate", type=int, default=165, help="words per minute")
    ap.add_argument("--out", default=str(ROOT / "artifacts/video"))
    ap.add_argument("--reuse-shots", action="store_true", help="skip capture; re-voice and re-assemble only")
    ap.add_argument("--chromium", help="path to a Chromium binary (default: Playwright's)")
    args = ap.parse_args()
    out = Path(args.out)
    shots = out / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(m, flush=True)  # noqa: E731
    if args.reuse_shots:
        facts = json.loads((shots / "facts.json").read_text())
    else:
        facts = asyncio.run(capture(args, shots, log))
    log(f"facts: {facts}")
    total = assemble(facts, shots, out, args.voice, args.rate, log)
    log(f"\nwrote {out / 'provenance.mp4'} ({total:.0f}s), {out / 'provenance.srt'}, shots in {shots}")
    if total > LIMIT_S:
        sys.exit(f"Over {LIMIT_S:.0f}s: raise --rate (now {args.rate}) or record your own voice files.")


if __name__ == "__main__":
    main()
