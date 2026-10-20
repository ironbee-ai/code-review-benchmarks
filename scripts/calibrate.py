"""Calibration of our judging panel against the benchmark's own judge. The candidates GPT-5.2 extracted for some of
the benchmark's products (results/openai_gpt-5.2/candidates.json in the benchmark) go through our panel by the same
steps that judged our models (Gemini, Sol, Opus; dedup by the first, majority vote), and both verdicts are scored the
same way (core profile, F2). Judged records go to results/calibration/, apart from the benchmark's results.
Usage: python scripts/calibrate.py qodo-extended-v2 coderabbit gitlab"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crbench import judge as J
from crbench import judge_proxy as JP
from crbench.config import Model, load_judges
from crbench.dataset import load_set
from crbench.env import load_env
from crbench.metrics import golden_lookup, score

M = ROOT / "work" / "martian" / "offline"
OUT = ROOT / "results" / "calibration"
JUDGE_DIR = M / "results" / "openai_gpt-5.2"


def main(products: list[str]) -> None:
    load_env()
    J.JUDGED = OUT / "judged"            # our judged records for these products, apart from the benchmark's
    JP.USAGE_DIR = OUT / "judge_usage"         # and their judge calls
    with open(JUDGE_DIR / "candidates.json") as f:
        cands = json.load(f)
    with open(JUDGE_DIR / "evaluations.json") as f:
        theirs = json.load(f)
    pr_of = {e["golden_url"]: e["id"] for e in load_set(ROOT / "data" / "sets" / "full.json")}
    pool = load_judges()
    tools, runs_by_tool, models = [], {}, {}
    for prod in products:
        mid = f"martian-{prod}"
        tool = f"{mid}__default__r1"
        models[mid] = Model(id=mid, family="product", route="none", model="-", tiers={"default": {}}, sets=[])
        runs = []
        for url, by_tool in theirs.items():
            if prod not in by_tool or url not in pr_of:
                continue
            findings = [{"title": "", "body": c["text"], "file": c.get("path"), "line": c.get("line")} for c in (cands.get(url) or {}).get(prod) or []]
            runs.append({"run_id": f"{tool}@{pr_of[url]}", "pr_id": pr_of[url], "golden_url": url, "status": "ok", "findings": findings})
        tools.append(tool)
        runs_by_tool[tool] = runs
        print(f"{prod}: {len(runs)} PRs, {sum(len(r['findings']) for r in runs)} candidates", flush=True)
    records = J.judge_tools(tools, runs_by_tool, models, pool, shards=8)

    spec = importlib.util.spec_from_file_location("sp", M / "analysis" / "score_profiles.py")
    sp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sp)
    gc = sp._load_golden_categories(M / "results")
    lookup = golden_lookup()
    summary = {}
    for prod, tool in zip(products, tools):
        rec = records[tool]
        urls = set(rec["voted"])
        mine = score(rec["voted"], "core", 2.0, lookup, ci=False)
        theirs_tool = {u: {prod: theirs[u][prod]} for u in urls}
        their = sp.score_tools(theirs_tool, gc, "core", 2.0)[prod]
        # golden-level agreement between their verdict and our panel's
        agree = n = both = only_ours = only_theirs = 0
        for u in urls:
            ours_tp = {x["golden_comment"] for x in rec["voted"][u].get("true_positives", [])}
            their_tp = {x.get("golden_comment") for x in theirs[u][prod].get("true_positives", [])}
            goldens = ours_tp | {x["golden_comment"] for x in rec["voted"][u].get("false_negatives", [])}
            for g in goldens:
                n += 1
                o, t = g in ours_tp, g in their_tp
                agree += o == t
                both += o and t
                only_ours += o and not t
                only_theirs += t and not o
        per_judge = {}
        for jid, rows in rec["per_judge"].items():
            per_judge[jid] = sp.score_tools({u: {prod: r} for u, r in rows.items() if u in urls}, gc, "core", 2.0)[prod]["fbeta"]
        summary[prod] = {"prs": len(urls), "ours": {k: mine[k] for k in ("precision", "recall", "f1", "fbeta", "tp", "fp", "fn")},
                         "gpt_5_2": {k: their[k] for k in ("precision", "recall", "f1", "fbeta", "tp", "fp", "fn")},
                         "golden_agreement": agree / n if n else None, "goldens": n, "found_by_both": both,
                         "found_only_by_ours": only_ours, "found_only_by_gpt_5_2": only_theirs, "our_judges_alone_f2": per_judge}
        print(f"{prod}: ours F2 {100 * mine['fbeta']:.1f} (P {100 * mine['precision']:.1f} R {100 * mine['recall']:.1f}) | "
              f"GPT-5.2 F2 {100 * their['fbeta']:.1f} (P {100 * their['precision']:.1f} R {100 * their['recall']:.1f}) | "
              f"golden agreement {100 * agree / max(n, 1):.1f}% (only ours {only_ours}, only GPT-5.2 {only_theirs})", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
