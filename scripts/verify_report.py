"""Independent check of a crbench report: re-vote every (pull request, repeat) from the three judges' raw rows, score
the votes with the benchmark's own analysis/score_profiles.py, recompute usage and cost from the run files and
configs/pricing.yaml, and compare with the report's CSVs and its markdown table. What the report covers (set, pull
requests, repeats) is read from its meta.json. Usage: python scripts/verify_report.py <report directory name>."""
import csv
import importlib.util
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / sys.argv[1]
SP_PATH = ROOT / "work/lanes/grok-4.7/0/offline/analysis/score_profiles.py"


def load(path):
    with open(path) as f:
        return json.load(f)


def rows(name):
    with open(REPORT / name) as f:
        return list(csv.DictReader(f))


def cost(u, price, cached=True):
    """List-price dollars of one request; uncached: every input token at the input price. Long-context rates apply to
    the whole request when its prompt (input + cache reads + cache writes) is over the threshold."""
    prompt = u["input"] + u.get("cache_read", 0) + u.get("cache_write", 0)
    lc = price.get("long_context")
    if lc and prompt > lc["over"]:
        price = {**price, **lc}
    if cached:
        return (u["input"] * price["input"] + u["output"] * price["output"] + u.get("cache_read", 0) * (price["cache_read"] or price["input"])
                + u.get("cache_write", 0) * (price["cache_write"] or price["input"])) / 1e6
    return (prompt * price["input"] + u["output"] * price["output"]) / 1e6


def run_cost(run, price, cached=True):
    return sum(cost(c["usage"], price, cached) for c in run["calls"])


def ftext(f):
    t, b = f.get("title") or "", f.get("body") or ""
    return f"{t}\n\n{b}" if t and b and not b.startswith(t) else (b or t)


def close(a, b, tol=1e-9):
    if a in ("", None) and b in ("", None):
        return True
    if a in ("", None) or b in ("", None):
        return False
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


spec = importlib.util.spec_from_file_location("score_profiles", SP_PATH)
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)

meta = load(REPORT / "meta.json")
with open(ROOT / "configs/pricing.yaml") as fh:
    pricing = yaml.safe_load(fh)["models"]
golden = {}
for p in sorted((ROOT / "data/martian/golden_comments").glob("*.json")):
    for e in load(p):
        for gc in e.get("comments", []):
            golden[gc["comment"]] = {"category": gc.get("category"), "severity": gc.get("severity"), "url": e["url"]}
gcat = {k: v["category"] for k, v in golden.items()}
entries = load(ROOT / "data/sets" / f"{meta['set']}.json")
urls = {e["golden_url"] for e in entries if not meta["prs"] or e["id"] in meta["prs"]}

problems = []


def expect(cond, msg):
    if not cond:
        problems.append(msg)


configs = rows("configs.csv")
per_judge_csv = {r["config"]: r for r in rows("per_judge.csv")}
tables = {}
for name, key in (("recall_by_category.csv", "category"), ("recall_by_severity.csv", "severity"), ("precision_by_model_category.csv", "category")):
    t = defaultdict(dict)
    for r in rows(name):
        t[r["config"]][r[key]] = r
    tables[name] = t
slices = defaultdict(list)
for r in rows("slices.csv"):
    slices[r["config"]].append(r)

checked = 0
for c in configs:
    model, tier = c["model"], c["tier"]
    cfg, base = f"{model}/{tier}", f"{model}__{tier}"
    my_evals, judge_evals, runs, items = {}, defaultdict(dict), [], []
    hit, tot = {"category": defaultdict(int), "severity": defaultdict(int)}, {"category": defaultdict(int), "severity": defaultdict(int)}
    cand_tot, cand_fp = defaultdict(int), defaultdict(int)
    reps = 0
    for rep in meta["repeats"]:
        path = ROOT / "results/judged" / f"{base}__r{rep}.json"
        if not path.exists():
            continue
        reps += 1
        rec = load(path)
        judges = list(rec["per_judge"])
        expect(len(judges) == 3, f"{cfg} r{rep}: {len(judges)} judges")
        rep_runs = {r["golden_url"]: r for r in (load(p) for p in (ROOT / "results/runs" / model / tier).glob(f"*__r{rep}.json"))
                    if r.get("status") in ("ok", "parse_error")}
        runs.extend(rep_runs[u] for u in sorted(urls & set(rep_runs)))   # usage covers every run, judged or not
        voted_ok = {u for u, v in rec["voted"].items() if not v.get("incomplete")}
        for url in sorted(urls & set(rep_runs) & voted_ok):              # scores cover the PRs the panel voted on
            run = rep_runs[url]
            key = f"{url}#r{rep}"
            texts = [ftext(f) for f in run["findings"] if ftext(f).strip()]
            cat_of = {ftext(f): f.get("category") or "?" for f in run["findings"]}
            jr = {j: rec["per_judge"][j][url] for j in judges}
            want = {g for g, v in golden.items() if v["url"] == url}
            for j, r in jr.items():
                seen = {x["golden_comment"] for x in r["true_positives"] + r["false_negatives"]}
                expect(seen == want, f"{cfg} r{rep} {j}: goldens seen {len(seen)} != the benchmark's {len(want)}")
                expect(r["total_candidates"] == len(texts), f"{cfg} r{rep} {j}: total_candidates {r['total_candidates']} != findings {len(texts)}")
                expect(all(x["candidate"] in texts for x in r["false_positives"]), f"{cfg} r{rep} {j}: an FP text is not one of the run's findings")
                expect(all(x.get("matched_candidate") in (None, *texts) for x in r["true_positives"]), f"{cfg} r{rep} {j}: a matched text is not one of the run's findings")
                judge_evals[j][key] = {base: r}
            yes = {g: sum(1 for r in jr.values() if g in {x["golden_comment"] for x in r["true_positives"]}) for g in want}
            tps = [{"golden_comment": g} for g in sorted(want) if yes[g] >= 2]
            fns = [{"golden_comment": g} for g in sorted(want) if yes[g] < 2]
            fps = {t for t in set(texts) if sum(1 for r in jr.values() if t in {x["candidate"] for x in r["false_positives"]}) >= 2}
            my_evals[key] = {base: {"true_positives": tps, "false_negatives": fns, "fp": len(fps)}}
            v = rec["voted"][url]
            expect((v["tp"], v["fp"], v["fn"]) == (len(tps), len(fps), len(fns)), f"{cfg} r{rep}: voted {(v['tp'], v['fp'], v['fn'])} != mine {(len(tps), len(fps), len(fns))}")
            items.extend(yes.values())
            for g in want:
                for k in ("category", "severity"):
                    tot[k][golden[g][k] or "?"] += 1
                    hit[k][golden[g][k] or "?"] += yes[g] >= 2
            for t in set(texts):
                cand_tot[cat_of[t]] += 1
                cand_fp[cat_of[t]] += t in fps
    expect(reps == int(c["repeats"] or 0), f"{cfg}: report says {c['repeats']} repeats, judged files {reps}")
    if not my_evals:  # not judged (a run still missing or errored): the report leaves its scores empty
        expect(c["f2"] in ("", None), f"{cfg}: scores shown without judged runs")
        continue
    # the benchmark's scorer on my votes, all (pull request, repeat) items pooled
    for profile, pcol, rcol, fcol in (("core", "precision", "recall", "f1"), ("all", None, "recall_all", "f1_all")):
        s = sp.score_tools(my_evals, gcat, profile, 2.0)[base]
        if pcol:
            expect(close(c[pcol], s["precision"]), f"{cfg}: {profile} P {c[pcol]} != martian {s['precision']}")
        expect(close(c[rcol], s["recall"]), f"{cfg}: {profile} R {c[rcol]} != martian {s['recall']}")
        expect(close(c[fcol], s["f1"]), f"{cfg}: {profile} F1 {c[fcol]} != martian {s['f1']}")
        if profile == "core":
            expect(close(c["f2"], s["fbeta"]), f"{cfg}: F2 {c['f2']} != martian {s['fbeta']}")
            expect((int(c["tp"]), int(c["fp"]), int(c["fn"])) == (s["tp"], s["fp"], s["fn"]), f"{cfg}: counts {(c['tp'], c['fp'], c['fn'])} != martian {(s['tp'], s['fp'], s['fn'])}")
            core = s
    unanimous = sum(1 for y in items if y in (0, 3)) / len(items) if items else None
    expect(close(c["unanimous_golden"], unanimous), f"{cfg}: unanimous_golden {c['unanimous_golden']} != {unanimous}")
    for k, name in (("category", "recall_by_category.csv"), ("severity", "recall_by_severity.csv")):
        for v in tot[k]:
            got = tables[name][cfg].get(v)
            expect(got is not None and (int(got["tp"]), int(got["goldens"])) == (hit[k][v], tot[k][v]),
                   f"{cfg}: recall by {k} {v}: report {got and (got['tp'], got['goldens'])} != {(hit[k][v], tot[k][v])}")
    for v in cand_tot:
        got = tables["precision_by_model_category.csv"][cfg].get(v)
        expect(got is not None and (int(got["candidates"]), int(got["fp"])) == (cand_tot[v], cand_fp[v]),
               f"{cfg}: precision by category {v}: report {got and (got['candidates'], got['fp'])} != all findings {(cand_tot[v], cand_fp[v])}")
    if len(urls) == 1:  # one pull request: every slice is the whole
        for r in slices[cfg]:
            expect((int(r["tp"]), int(r["fp"]), int(r["fn"])) == (core["tp"], core["fp"], core["fn"]), f"{cfg}: slice {r['dimension']}={r['value']} differs from the whole")
    for j, ev in judge_evals.items():
        s = sp.score_tools(ev, gcat, "core", 2.0)[base]
        expect(close(per_judge_csv[cfg].get(f"f2_{j}"), s["fbeta"]), f"{cfg}: judge {j} F2 {per_judge_csv[cfg].get(f'f2_{j}')} != martian {s['fbeta']}")
    # usage and cost from the run files, request by request
    n, price = len(runs), pricing[model]
    expect(close(c["cost_per_pr"], sum(run_cost(r, price) for r in runs) / n, 1e-6), f"{cfg}: $/PR {c['cost_per_pr']} differs")
    expect(close(c["cost_uncached_per_pr"], sum(run_cost(r, price, False) for r in runs) / n, 1e-6), f"{cfg}: uncached $/PR differs")
    for col, k in (("input_per_pr", "input"), ("output_per_pr", "output"), ("cache_read_per_pr", "cache_read")):
        expect(close(c[col], sum(r["usage"].get(k, 0) for r in runs) / n), f"{cfg}: {col} {c[col]} != runs")
    known = [r["usage"]["reasoning"] for r in runs if r["usage"].get("reasoning") is not None]
    expect(close(c["reasoning_per_pr"], sum(known) / len(known) if known else None), f"{cfg}: reasoning/PR {c['reasoning_per_pr']} differs")
    expect(close(c["findings_per_pr"], sum(len(r["findings"]) for r in runs) / n), f"{cfg}: findings/PR differs")
    expect(close(c["latency_median_s"], statistics.median(r["latency_ms"] / 1000 for r in runs)), f"{cfg}: latency differs")
    for r in runs:
        for k in ("input", "output", "cache_read", "cache_write"):
            expect(sum((cl["usage"] or {}).get(k, 0) or 0 for cl in r["calls"]) == (r["usage"].get(k) or 0), f"{cfg}: calls' {k} do not add up")
    checked += 1

# the markdown table shows the CSV's numbers
md_rows = {}
for line in (REPORT / "report.md").read_text().split("\n## ")[1].splitlines():
    cells = [x.strip() for x in line.strip("|").split("|")]
    if len(cells) > 6 and cells[0] not in ("model", "---"):
        md_rows[(cells[0], cells[1])] = cells
for c in configs:
    cells = md_rows.get((c["model"], c["tier"]))
    want = [f"{100 * float(c[k]):.1f}" for k in ("precision", "recall", "f1", "f2")]
    expect(cells is not None and cells[2:6] == want, f"{c['model']}/{c['tier']}: markdown {cells and cells[2:6]} != csv {want}")

print(f"{checked} configurations, repeats {meta['repeats']}, {len(urls)} pull requests: checked against Martian's score_profiles.py and the run files")
print(f"{len(problems)} problems")
for p in problems:
    print(" -", p)
