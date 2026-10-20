"""How much more a pass will bill on OpenRouter, from how it is going: for each OpenRouter configuration, the billed cost
per run so far times the runs left (the trial's measured cost where a configuration has no run yet); for the Gemini
judge, the match calls its panels will make (findings x goldens, from the runs so far, the mean where a run is not
made yet) at its measured cost per call, minus what it has billed since the pass started.
Usage: python scripts/openrouter_need.py <repeats> <pass start, UTC, e.g. 2026-10-17T11:20>"""
import glob
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crbench.config import TIERS, configs_for, judges_for, load_judges, load_models, load_pricing, tier_params
from crbench.dataset import load_set
from crbench.metrics import run_cost
from crbench.usage_log import read_rows

GEMINI = "gemini-4-argon"
DEDUP_OVERHEAD = 1.15  # the dedup step's calls on top of the match calls (measured on the trial)


def need(repeats: list[int], since: str) -> dict:
    models = load_models()
    pool = load_judges()
    pricing = load_pricing()
    gold = {e["id"]: e["golden_count"] for e in load_set(ROOT / "data" / "sets" / "full.json")}
    by_id = {m.id: m for m in models}
    runs: dict[tuple, dict] = {}
    measured: dict[tuple, list] = {}   # list-price cost of every run of a (model, tier), on any route: the fallback
    for p in glob.glob(str(ROOT / "results" / "runs" / "*" / "*" / "*.json")):
        with open(p) as f:
            r = json.load(f)
        m = by_id.get(r.get("model_id"))
        current = m is not None and r.get("route") == m.route and r.get("params") == tier_params(m, r["tier"])[0] and r.get("provider_pin") == m.provider
        if r.get("status") in ("ok", "parse_error") and r.get("calls") and m is not None:
            measured.setdefault((m.id, r["tier"]), []).append(run_cost(r, pricing[m.id]))
        if r.get("repeat") in repeats and r.get("status") in ("ok", "parse_error") and current:
            runs[(r["model_id"], r["tier"], r["pr_id"], r["repeat"])] = r
    # Gemini's measured cost per match call (its judge log, billed)
    per_call = []
    rows = read_rows(ROOT / "results" / "judge_usage" / f"{GEMINI}.jsonl")[0]
    per_call = [x["cost_reported"] for x in rows if x.get("step") == "step3" and x.get("cost_reported")]
    gemini_call = statistics.mean(per_call) if per_call else 0.0015
    gemini_billed = sum(x.get("cost_reported") or 0 for x in rows if x["ts"] >= since)
    reviews_left = judge_total = 0.0
    detail = {}
    for set_name in ("full", "frontier"):
        prs = [e["id"] for e in load_set(ROOT / "data" / "sets" / f"{set_name}.json")]
        for m, t in configs_for(models, list(TIERS), set_name):
            made = [runs[(m.id, t, pr, rep)] for pr in prs for rep in repeats if (m.id, t, pr, rep) in runs]
            left = len(prs) * len(repeats) - len(made)
            if m.route == "openrouter" and left:
                billed = [r["cost_reported"] for r in made if r.get("cost_reported") is not None]
                per_run = statistics.mean(billed) if billed else statistics.mean(measured.get((m.id, t)) or [0.1])
                reviews_left += per_run * left
                detail[f"{m.id}/{t}"] = round(per_run * left, 2)
            if GEMINI in [j.id for j in judges_for(m.family, pool)]:
                found = {(r["pr_id"], r["repeat"]): r.get("finding_count") or 0 for r in made}
                mean_f = statistics.mean(found.values()) if found else 5
                judge_total += sum(found.get((pr, rep), mean_f) * gold[pr] for pr in prs for rep in repeats) * gemini_call * DEDUP_OVERHEAD
    judge_left = max(0.0, judge_total - gemini_billed)
    return {"reviews_left": reviews_left, "gemini_judge_left": judge_left, "total_left": reviews_left + judge_left,
            "gemini_call": gemini_call, "detail": dict(sorted(detail.items(), key=lambda kv: -kv[1]))}


if __name__ == "__main__":
    reps = [int(x) for x in sys.argv[1].split("-")]
    reps = list(range(reps[0], reps[-1] + 1))
    n = need(reps, sys.argv[2])
    print(f"still to bill on OpenRouter: ~${n['total_left']:.0f} (reviews ~${n['reviews_left']:.0f}, Gemini judge ~${n['gemini_judge_left']:.0f};"
          f" Gemini ${n['gemini_call'] * 1000:.2f} per 1,000 match calls)")
    for k, v in list(n["detail"].items())[:10]:
        print(f"  {k}: ${v:.2f}")
