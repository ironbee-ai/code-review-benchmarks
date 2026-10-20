"""A short status of a running pass: runs made and left per set, pull requests and configurations complete, errors,
configurations judged, money spent since the pass started (list price; OpenRouter's billed cost), the OpenRouter
balance and what the pass is still expected to bill there.
Usage: python scripts/pass_status.py <repeats> <pass start, UTC, e.g. 2026-10-17T11:20>"""
import glob
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import httpx
from openrouter_need import need

from crbench.config import TIERS, configs_for, judges_for, load_judges, load_models, load_pricing, tier_params, tool_name
from crbench.dataset import load_set
from crbench.env import load_env
from crbench.metrics import cost_list, run_cost
from crbench.usage_log import read_rows

load_env()
reps_arg, since = sys.argv[1], sys.argv[2]
lo, hi = (int(x) for x in (reps_arg.split("-") * 2)[:2])
reps = list(range(lo, hi + 1))
models, pricing = load_models(), load_pricing()
by_id = {m.id: m for m in models}

done, errors, slow = defaultdict(set), Counter(), {}
spent = Counter()
for p in glob.glob(str(ROOT / "results" / "runs" / "*" / "*" / "*.json")):
    with open(p) as f:
        r = json.load(f)
    if r.get("repeat") not in reps:
        continue
    key = (r["model_id"], r["tier"])
    m = by_id.get(r["model_id"])
    current = m is not None and r.get("route") == m.route and r.get("params") == tier_params(m, r["tier"])[0] and r.get("provider_pin") == m.provider
    if r.get("status") in ("ok", "parse_error") and current:   # a run made on another route or with other parameters is redone
        done[key].add((r["pr_id"], r["repeat"]))
    elif r.get("status") == "error":
        errors[f"{r['model_id']}/{r['tier']}"] += 1
    if r.get("started_at", "") >= since and r.get("calls"):
        route = by_id[r["model_id"]].route
        spent["bedrock" if route.startswith("bedrock") else "openrouter_list"] += run_cost(r, pricing.get(r["model_id"])) or 0
        spent["openrouter_billed"] += r.get("cost_reported") or 0

def judged_all(tool: str, urls: set[str]) -> bool:
    """Every pull request of the set has a complete panel vote in the tool's judged record."""
    path = ROOT / "results" / "judged" / f"{tool}.json"
    if not path.exists():
        return False
    with open(path) as f:
        voted = json.load(f)["voted"]
    return all(u in voted and not voted[u].get("incomplete") for u in urls)


lines = [f"Status at {time.strftime('%H:%M')}"]
total_made = total_all = 0
for set_name in ("full", "frontier"):
    prs = [e["id"] for e in load_set(ROOT / "data" / "sets" / f"{set_name}.json")]
    cfgs = configs_for(models, list(TIERS), set_name)
    want = {(pr, rep) for pr in prs for rep in reps}
    made = sum(len(done[(m.id, t)] & want) for m, t in cfgs)
    total_made += made
    total_all += len(cfgs) * len(want)
    complete_cfgs = [f"{m.id}/{t}" for m, t in cfgs if want <= done[(m.id, t)]]
    complete_prs = sum(1 for w in want if all(w in done[(m.id, t)] for m, t in cfgs))
    urls = {e["golden_url"] for e in load_set(ROOT / "data" / "sets" / f"{set_name}.json")}
    judged = sum(1 for m, t in cfgs if all(judged_all(tool_name(m.id, t, rep), urls) for rep in reps))
    lines.append(f"{set_name}: runs {made}/{len(cfgs) * len(want)} ({len(cfgs) * len(want) - made} left); PRs done by every configuration "
                 f"{complete_prs}/{len(want)}; configurations done {len(complete_cfgs)}/{len(cfgs)}, judged {judged}")
    if set_name == "full":
        left = sorted(((len(want - done[(m.id, t)]), f"{m.id}/{t}") for m, t in cfgs if want - done[(m.id, t)]), reverse=True)
        slow = left[:6]
# judging, from the lanes (each judge's own rows; a configuration is judged when its three judges have every PR)
lane_rows: dict[tuple[str, str], set[str]] = defaultdict(set)
for path in glob.glob(str(ROOT / "work" / "lanes" / "*" / "*" / "offline" / "results" / "*" / "evaluations.json")):
    judge_id = Path(path).parts[-6]
    try:
        with open(path) as f:
            ev = json.load(f)
    except (json.JSONDecodeError, OSError):
        continue
    for url, tools in ev.items():
        for tname, row in tools.items():
            if not row.get("errors_count"):
                lane_rows[(judge_id, tname)].add(url)
pool_obj = load_judges()
judging_lines = []
for set_name in ("full", "frontier"):
    urls = {e["golden_url"] for e in load_set(ROOT / "data" / "sets" / f"{set_name}.json")}
    want = {(pr, rep) for pr in (e["id"] for e in load_set(ROOT / "data" / "sets" / f"{set_name}.json")) for rep in reps}
    n_judged = n_running = n_waiting = 0
    detail = []
    for m, t in configs_for(models, list(TIERS), set_name):
        tool = tool_name(m.id, t, reps[0])
        triple = [j.id for j in judges_for(m.family, pool_obj)]
        prog = {j: len(lane_rows[(j, tool)] & urls) for j in triple}
        if not want <= done[(m.id, t)]:
            n_waiting += 1
        elif all(v == len(urls) for v in prog.values()):
            n_judged += 1
        else:
            n_running += 1
            detail.append(f"{m.id}/{t} (" + ", ".join(f"{j.split('-')[0]} {v}" for j, v in prog.items()) + f" of {len(urls)})")
    judging_lines.append(f"judging {set_name}: {n_judged} judged, {n_running} being judged, {n_waiting} waiting for reviews"
                         + (": " + "; ".join(detail) if detail else ""))

lines.append(f"overall runs {total_made}/{total_all} ({100 * total_made / total_all:.0f}%); most runs left: "
             + ", ".join(f"{c} {n}" for n, c in slow))
lines.extend(judging_lines)
running = [ln for ln in os.popen("ps -axo etime=,command=").read().splitlines() if "crbench judge" in ln and "grep" not in ln]
lines.append("judging pass: " + (f"running for {running[0].split()[0]} ({'frontier' if 'frontier' in running[0] else 'full'})" if running
                                  else "none running; the next starts within 30 minutes"))
lines.append("errors: " + (", ".join(f"{k} {v}" for k, v in errors.items()) if errors else "none"))

judge_list = judge_billed = 0.0
pool = {j.id for j in load_judges().pool}
for path in glob.glob(str(ROOT / "results" / "judge_usage" / "*.jsonl")):
    jid = Path(path).stem
    for c in read_rows(path)[0]:
        if c.get("ts", "") >= since and jid in pool:
            judge_list += cost_list(c.get("usage") or {}, pricing.get(jid)) or 0
            judge_billed += c.get("cost_reported") or 0
lines.append(f"spent since start (list price): reviews ${spent['bedrock'] + spent['openrouter_list']:.2f} "
             f"(Bedrock ${spent['bedrock']:.2f}, OpenRouter ${spent['openrouter_list']:.2f}), judging ${judge_list:.2f}; "
             f"OpenRouter billed ${spent['openrouter_billed'] + judge_billed:.2f}")
key = os.environ.get("OPENROUTER_API_KEY")
try:
    d = httpx.get("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {key}"}, timeout=20).json()["data"]
    left = d["total_credits"] - d["total_usage"]
    n = need(reps, since)
    lines.append(f"OpenRouter: ${left:.2f} left; still to bill ~${n['total_left']:.0f} (reviews ~${n['reviews_left']:.0f}, "
                 f"Gemini judge ~${n['gemini_judge_left']:.0f}) -> {'enough' if left >= n['total_left'] else f'short by ~${n['total_left'] - left:.0f}'}")
except Exception as e:  # noqa: BLE001
    lines.append(f"OpenRouter: balance not read ({type(e).__name__})")
log = ROOT / "results" / f"pass_r{reps_arg}" / "pass.log"
if log.exists():
    lines.append("pass log: " + log.read_text().splitlines()[-1])
print("\n".join(lines))
