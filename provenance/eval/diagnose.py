"""Why does an arm auto-close what it does? Separation and threshold diagnostics from one run's jsonl.

    python -m provenance.eval.diagnose artifacts/eval/A3/<run_id>.jsonl [--alerts artifacts/alerts.jsonl]

No model calls. Answers two questions that need different fixes:
  * does the model *rank* benign above suspicious (AUROC), and only its scale is off, so a
    calibrated threshold would help; or
  * does it not separate them at all, so it needs better evidence?

EvalRow.confidence is P(decision correct), so P(false positive) = confidence for an
auto-close and 1 - confidence for an escalation. Error rows are left out of the
separation statistics and counted separately.

A threshold picked here is fitted to these labels. Report it only after checking it,
unchanged, on alerts it was not picked on.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from provenance.eval.metrics import ANALYST_MINUTES_PER_ALERT
from provenance.eval.results import EvalRow, read_jsonl

THRESHOLDS = [round(0.05 * i, 2) for i in range(1, 20)]


def p_false_positive(r: EvalRow) -> float | None:
    if r.decision == "error" or r.confidence is None:
        return None
    return r.confidence if r.auto_closed else 1 - r.confidence


def auroc(benign: list[float], suspicious: list[float]) -> float | None:
    """P(a random benign alert scores a higher P(FP) than a random suspicious one); ties count half."""
    if not benign or not suspicious:
        return None
    wins = sum((b > s) + 0.5 * (b == s) for b in benign for s in suspicious)
    return wins / (len(benign) * len(suspicious))


def quantiles(xs: list[float]) -> dict[str, float] | None:
    if not xs:
        return None
    s = sorted(xs)

    def q(p: float) -> float:
        return round(s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))], 3)

    return {"min": q(0), "p25": q(0.25), "median": q(0.5), "p75": q(0.75), "max": q(1)}


def sweep(scored: list[tuple[float, bool]], thresholds=THRESHOLDS) -> list[dict]:
    """At each threshold: how many would auto-close, and how many of those are suspicious."""
    n = len(scored)
    out = []
    for t in thresholds:
        closed = [sus for p, sus in scored if p >= t]
        out.append({"theta": t, "auto_close": len(closed), "suspicious_auto_closed": sum(closed),
                    "auto_close_rate": round(len(closed) / n, 3) if n else 0.0,
                    "analyst_hours_saved": round((len(closed) - sum(closed)) * ANALYST_MINUTES_PER_ALERT / 60, 2)})
    return out


def best_safe(rows: list[dict]) -> dict | None:
    """The threshold with the most auto-closes and zero suspicious auto-closed; among equals the
    highest, which leaves the most margin above the suspicious scores."""
    safe = [r for r in rows if r["suspicious_auto_closed"] == 0 and r["auto_close"] > 0]
    return max(safe, key=lambda r: (r["auto_close"], r["theta"])) if safe else None


def diagnose(rows: list[EvalRow], rules: dict[str, str] | None = None) -> dict:
    rules = rules or {}
    scored = [(p, r.truly_suspicious, r) for r in rows if (p := p_false_positive(r)) is not None]
    benign = [p for p, sus, _ in scored if not sus]
    suspicious = [p for p, sus, _ in scored if sus]
    pairs = [(p, sus) for p, sus, _ in scored]
    table = sweep(pairs)
    by_rule: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for p, sus, r in scored:
        by_rule[rules.get(r.alert_id, "unknown")].append((p, sus))
    gate = {"benign": Counter(), "suspicious": Counter()}
    for r in rows:
        for name in r.gate_failed or []:
            gate["suspicious" if r.truly_suspicious else "benign"][name] += 1
    return {
        "arm": rows[0].arm if rows else None, "run_id": rows[0].run_id if rows else None,
        "n": len(rows), "errors": sum(r.decision == "error" for r in rows),
        "unverified": sum(r.decision != "error" and r.citation_coverage < 1.0 for r in rows),
        "scored": len(scored), "benign": len(benign), "suspicious": len(suspicious),
        "p_fp_benign": quantiles(benign), "p_fp_suspicious": quantiles(suspicious),
        "auroc": None if (a := auroc(benign, suspicious)) is None else round(a, 3),
        "sweep": table, "best_zero_miss": best_safe(table),
        "by_rule": {k: {"n": len(v), "suspicious": sum(s for _, s in v),
                        "auroc": None if (a := auroc([p for p, s in v if not s], [p for p, s in v if s])) is None
                        else round(a, 3),
                        "best_zero_miss": best_safe(sweep(v))}
                    for k, v in sorted(by_rule.items())},
        "gate_failed": {k: dict(v) for k, v in gate.items()} if any(gate.values()) else None,
    }


def _alert_meta(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {(a := json.loads(line))["alert_id"]: a for line in path.read_text().splitlines() if line.strip()}


def _rules(path: Path) -> dict[str, str]:
    return {k: v.get("rule", "unknown") for k, v in _alert_meta(path).items()}


def label_source(meta: dict) -> str:
    """saml_d, or sanctions_exposure with its cohort (new = designated after the archived list)."""
    src = meta.get("label_source") or "unknown"
    if src == "sanctions_exposure":
        return f"sanctions ({'new' if meta.get('designated_after_archive') else 'old'})"
    return src


def detail(rows: list[EvalRow], meta: dict[str, dict], theta: float = 0.90) -> list[dict]:
    """Every row the model would close at theta, plus every suspicious row: what it was and what stopped it."""
    out = []
    for r in rows:
        p = p_false_positive(r)
        if not ((p is not None and p >= theta) or r.truly_suspicious):
            continue
        m = meta.get(r.alert_id, {})
        out.append({"alert_id": r.alert_id, "suspicious": r.truly_suspicious, "label_source": label_source(m),
                    "rule": m.get("rule", "unknown"), "p_fp": None if p is None else round(p, 2),
                    "decision": r.decision, "gate_failed": r.gate_failed})
    return sorted(out, key=lambda x: (not x["suspicious"], -(x["p_fp"] or 0)))


def render_detail(items: list[dict], theta: float) -> str:
    out = [f"rows with P(FP) >= {theta} and every suspicious row:",
           f"  {'alert':16s} {'label':10s} {'source':18s} {'rule':20s} {'P(FP)':>5s}  {'decision':10s} gate failed"]
    for x in items:
        out.append(f"  {x['alert_id']:16s} {'SUSPICIOUS' if x['suspicious'] else 'benign':10s} {x['label_source']:18s} "
                   f"{x['rule']:20s} {x['p_fp'] if x['p_fp'] is not None else '-':>5}  {x['decision']:10s} "
                   f"{', '.join(x['gate_failed']) if x['gate_failed'] else ('-' if x['gate_failed'] is None else 'none')}")
    return "\n".join(out)


def render(d: dict) -> str:
    out = [f"{d['arm']} {d['run_id']}: n={d['n']} scored={d['scored']} (benign {d['benign']}, suspicious "
           f"{d['suspicious']}), errors={d['errors']}, unverified narratives={d['unverified']}",
           f"P(false positive) benign:     {d['p_fp_benign']}",
           f"P(false positive) suspicious: {d['p_fp_suspicious']}",
           f"AUROC (benign ranked above suspicious): {d['auroc']}   0.5 = no separation, 1.0 = perfect", "",
           "theta  auto-close  suspicious-closed  hours-saved"]
    out += [f"{r['theta']:5.2f}  {r['auto_close']:10d}  {r['suspicious_auto_closed']:17d}  {r['analyst_hours_saved']:11.2f}"
            for r in d["sweep"]]
    b = d["best_zero_miss"]
    out.append("")
    out.append(f"most auto-closes with zero suspicious closed: theta {b['theta']} -> {b['auto_close']} "
               f"({b['auto_close_rate']:.0%})" if b else "no threshold auto-closes anything without closing a suspicious alert")
    out.append("")
    out.append("by rule:")
    for k, v in d["by_rule"].items():
        bz = v["best_zero_miss"]
        out.append(f"  {k:22s} n={v['n']:3d} suspicious={v['suspicious']:3d} auroc={v['auroc']} "
                   f"best zero-miss={'theta %s -> %d' % (bz['theta'], bz['auto_close']) if bz else 'none'}")
    if d["gate_failed"]:
        out.append("")
        out.append(f"gate conditions failed: {d['gate_failed']}")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path, help="an eval run's jsonl")
    ap.add_argument("--alerts", type=Path, default=Path("artifacts/alerts.jsonl"), help="for the per-rule breakdown")
    ap.add_argument("--detail", action="store_true", help="list closable and suspicious rows with label source and gate failures")
    ap.add_argument("--theta", type=float, default=0.90, help="P(false positive) cut-off for --detail")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows, meta = read_jsonl(a.run), _alert_meta(a.alerts)
    d = diagnose(rows, {k: v.get("rule", "unknown") for k, v in meta.items()})
    if a.detail:
        d["detail"] = detail(rows, meta, a.theta)
    if a.json:
        print(json.dumps(d, indent=2))
        return
    print(render(d))
    if a.detail:
        print()
        print(render_detail(d["detail"], a.theta))


if __name__ == "__main__":
    main()
