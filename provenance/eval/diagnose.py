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


def _rules(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {(a := json.loads(line))["alert_id"]: a.get("rule", "unknown")
            for line in path.read_text().splitlines() if line.strip()}


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
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = diagnose(read_jsonl(a.run), _rules(a.alerts))
    print(json.dumps(d, indent=2) if a.json else render(d))


if __name__ == "__main__":
    main()
