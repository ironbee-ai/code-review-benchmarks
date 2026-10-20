"""Control run for the review prompt (2026-10-17). The review prompt of pass 1 lists the issue types the
benchmark's core profile counts and tells the model to leave out style and speculation, the two it does not. Here
the four best configurations of the first group review the fifty pull requests again with a neutral system prompt
(configs/prompts/review_system_neutral.md: no list of issue types, no exclusions, no category field); everything else
as in pass 1. Runs go to results/control/runs, judged records to results/control/judged, and the tools are named
control-<model>__<tier>__r1 in the judge lanes, so nothing of pass 1 is touched. Judged by the same panel.
Usage: python scripts/control_prompt.py run [model/tier ...] | judge | score"""
import asyncio
import csv
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crbench import judge as J
from crbench import judge_proxy as JP
from crbench import runner as R
from crbench.config import load_judges, load_models, load_runs, tool_name
from crbench.dataset import load_set
from crbench.env import load_env
from crbench.metrics import golden_lookup, score

OUT = ROOT / "results" / "control"
CONFIGS = ["claude-sonnet-5.5/low", "muse-spark-1.3/low", "claude-opus-5.5/default", "grok-4.7/low"]
R.RUNS = OUT / "runs"                # run_path() reads this at call time
J.JUDGED = OUT / "judged"
JP.USAGE_DIR = OUT / "judge_usage"          # judge calls logged apart from the benchmark's (they were not, at first; moved by hand)


def cfg():
    c = load_runs()
    return replace(c, prompt=replace(c.prompt, system=ROOT / "configs" / "prompts" / "review_system_neutral.md"))


def run(selected: list[str]) -> None:
    models = {m.id: m for m in load_models()}
    c = cfg()

    async def all_of():
        await asyncio.gather(*(R.run_matrix([models[mt.split("/")[0]]], [mt.split("/")[1]], "full", c, [1]) for mt in selected))
    asyncio.run(all_of())


def judge() -> dict:
    models = {m.id: m for m in load_models()}
    urls = {e["golden_url"] for e in load_set(cfg().sets["full"])}
    tools, runs_by_tool, by_id = [], {}, {}
    for mt in CONFIGS:
        mid, tier = mt.split("/")
        runs = [r for r in R.runs_of(mid, tier) if r and r.get("repeat") == 1 and r.get("golden_url") in urls]
        bad = [r["pr_id"] for r in runs if r.get("status") not in ("ok", "parse_error")]
        if len(runs) != len(urls) or bad:
            raise SystemExit(f"{mt}: {len(runs)} of {len(urls)} runs, not done: {bad}")
        cid = f"control-{mid}"
        by_id[cid] = replace(models[mid], id=cid)            # same family, so the same three judges as in pass 1
        t = tool_name(cid, tier, 1)
        tools.append(t)
        runs_by_tool[t] = runs
    return J.judge_tools(tools, runs_by_tool, by_id, load_judges(), shards=8)


def score_all() -> None:
    lookup = golden_lookup()
    with open(ROOT / "reports" / "passes" / "full-r1" / "configs.csv") as f:      # pass 1, as the control was run against it
        base = {f"{c['model']}/{c['tier']}": {k: float(c[k]) for k in ("precision", "recall", "f1", "f2", "findings_per_pr")}
                for c in csv.DictReader(f)}
    out = {}
    for mt in CONFIGS:
        mid, tier = mt.split("/")
        rec = json.loads((J.JUDGED / f"{tool_name('control-' + mid, tier, 1)}.json").read_text())
        s = score(rec["voted"], "core", 2.0, lookup, ci=False)
        runs = [r for r in R.runs_of(mid, tier) if r and r.get("repeat") == 1]
        fpr = sum(len(r.get("findings") or []) for r in runs) / len(runs)
        b = base[mt]
        out[mt] = {"neutral": {k: s[k] for k in ("precision", "recall", "f1", "fbeta", "tp", "fp", "fn")}, "findings_per_pr": fpr,
                   "pass1": {"precision": b["precision"], "recall": b["recall"], "f1": b["f1"], "fbeta": b["f2"], "findings_per_pr": b["findings_per_pr"]}}
        print(f"{mt:26} pass 1 F2 {100 * b['f2']:5.1f} (P {100 * b['precision']:4.1f} R {100 * b['recall']:4.1f}, {b['findings_per_pr']:.1f}/PR) | "
              f"neutral F2 {100 * s['fbeta']:5.1f} (P {100 * s['precision']:4.1f} R {100 * s['recall']:4.1f}, {fpr:.1f}/PR)")
    (OUT / "summary.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    load_env()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run(sys.argv[2:] or CONFIGS)
    elif cmd == "judge":
        judge()
        score_all()
    elif cmd == "score":
        score_all()
