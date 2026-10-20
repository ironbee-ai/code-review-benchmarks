"""The analysis behind the write-up, from the exported tables (results/dataset, `crbench export`): scores per
configuration recomputed and checked against the report, paired-bootstrap tie groups, the three views, cost and
speed (Pareto, cost per true positive), effort curves, breakdowns (golden category and severity, language,
repository, size, application stack, change type, difficulty), noise, complementarity, judge robustness and
operations. Writes reports/<report>/analysis.json.
With several repeats, counts are pooled per (configuration, PR) as the report pools them, the bootstrap resamples
pull requests (a PR's repeats move together), and a repeat-stability section compares the repeats.
Usage: python scripts/analyze.py <full report dir> <frontier view dir> [repeats, e.g. 1-3]   (e.g. full-r123 frontier-view-full-r123 1-3)"""
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "results" / "dataset"
REPORT, FRONTIER = ROOT / "reports" / sys.argv[1], ROOT / "reports" / sys.argv[2]
BETA, B, RNG = 2.0, 4000, np.random.default_rng(7)
_r = sys.argv[3] if len(sys.argv) > 3 else "1"
REPS = [str(x) for x in (range(int(_r.split("-")[0]), int(_r.split("-")[1]) + 1) if "-" in _r else [int(v) for v in _r.split(",")])]


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def fb(p, r, beta):
    return (1 + beta * beta) * p * r / (beta * beta * p + r) if (beta * beta * p + r) > 0 else 0.0


runs = [r for r in rows(D / "runs.csv") if r["repeat"] in REPS]
golds = {g["golden"]: g for g in rows(D / "goldens.csv")}
prs = {p["pr"]: p for p in rows(D / "prs.csv")}
gres = [g for g in rows(D / "golden_results.csv") if g["repeat"] in REPS]
finds = [f for f in rows(D / "findings.csv") if f["repeat"] in REPS]
models_tab = {m["model"]: m for m in rows(D / "models.csv")}
report_cfg = {(r["model"], r["tier"]): r for r in rows(REPORT / "configs.csv")}
frontier_set = {p for p, v in prs.items() if v["in_frontier"] == "True"}
CORE = {g for g, v in golds.items() if v["in_core"] == "True"}
cfg_key = lambda r: (r["model"], r["tier"])
configs = sorted({cfg_key(r) for r in runs})
pr_list = sorted(prs)
out: dict = {"profile": "core", "beta": BETA, "repeats": REPS}

# ---- per (config, PR) counts: TP/FN over core goldens, FP over findings the panel voted false positives
tp = defaultdict(int); fn = defaultdict(int); fp = defaultdict(int); found_by = defaultdict(set)
found_by_rep = defaultdict(lambda: defaultdict(set))       # repeat -> golden -> configurations
rep_tp = defaultdict(int); rep_fn = defaultdict(int); rep_fp = defaultdict(int)  # per (config, PR, repeat)
for g in gres:
    if g["golden"] in CORE:
        (tp if g["found"] == "True" else fn)[(cfg_key(g), g["pr"])] += 1
        (rep_tp if g["found"] == "True" else rep_fn)[(cfg_key(g), g["pr"], g["repeat"])] += 1
    if g["found"] == "True":
        found_by[g["golden"]].add(cfg_key(g))
        found_by_rep[g["repeat"]][g["golden"]].add(cfg_key(g))
for f in finds:
    if f["panel"] == "false_positive":
        fp[(cfg_key(f), f["pr"])] += 1
        rep_fp[(cfg_key(f), f["pr"], f["repeat"])] += 1
run_of = {(cfg_key(r), r["pr"]): r for r in runs}


def counts(cfg, prset):
    return np.array([[tp[(cfg, p)], fp[(cfg, p)], fn[(cfg, p)]] for p in prset], dtype=float)


def score(c):
    t, f_, n = c.sum(axis=0)
    p = t / (t + f_) if t + f_ else 0.0
    r = t / (t + n) if t + n else 0.0
    return p, r, fb(p, r, 1), fb(p, r, BETA)


def boot(cfgs, prset, parts=None):
    """Paired bootstrap over pull requests: one resample of PRs per draw, shared by every configuration. F2 per draw;
    `parts`, if given, also receives each configuration's precision and recall per draw."""
    prset = list(prset)
    mats = {c: counts(c, [p for p in prset]) for c in cfgs}
    idx = RNG.integers(0, len(prset), size=(B, len(prset)))
    res = {}
    for c, m in mats.items():
        s = m[idx].sum(axis=1)             # B x 3
        t, f_, n = s[:, 0], s[:, 1], s[:, 2]
        p = np.divide(t, t + f_, out=np.zeros_like(t), where=(t + f_) > 0)
        r = np.divide(t, t + n, out=np.zeros_like(t), where=(t + n) > 0)
        d = BETA * BETA * p + r
        if parts is not None:
            parts[c] = {"precision": p, "recall": r}
        res[c] = np.divide((1 + BETA * BETA) * p * r, d, out=np.zeros_like(d), where=d > 0)
    return res


# ---- 1. integrity: recomputed scores against the report, one run per (config, PR), goldens counted once
full_cfgs = [c for c in configs if models_tab[c[0]]["sets"].find("full") >= 0]
integrity = {"runs": len(runs), "configs": len(configs), "mismatches": []}
for c in full_cfgs:
    p, r, f1, f2 = score(counts(c, pr_list))
    rep = report_cfg.get(c)
    if rep is None or abs(float(rep["f2"] or 0) - f2) > 1e-9 or abs(float(rep["precision"] or 0) - p) > 1e-9:
        integrity["mismatches"].append([*c, rep and rep["f2"], f2])
per_pair = Counter((cfg_key(r), r["pr"], r["repeat"]) for r in runs)
integrity["duplicate_runs"] = [k for k, v in per_pair.items() if v > 1]
gcount = Counter((cfg_key(g), g["pr"], g["repeat"]) for g in gres)
integrity["golden_rows_mismatch"] = [[*k[0], k[1], k[2], v, int(prs[k[1]]["goldens"])] for k, v in gcount.items() if v != int(prs[k[1]]["goldens"])]
fid = Counter(f["finding"] for f in finds)
integrity["duplicate_finding_ids"] = sum(1 for v in fid.values() if v > 1)
dup_text = Counter((f["run"], f["title"], f["body"]) for f in finds)
integrity["identical_findings_within_a_run"] = sum(v - 1 for v in dup_text.values() if v > 1)
rid = Counter(c["response_id"] for c in rows(D / "calls.csv") if c["response_id"] and c["run"].split("@")[0].rpartition("__r")[2] in REPS)
integrity["response_ids_seen_twice"] = sum(1 for v in rid.values() if v > 1)
integrity["statuses"] = dict(Counter(r["status"] for r in runs))
integrity["salvaged"] = sum(1 for r in runs if r.get("salvaged") == "True")
integrity["panel_verdicts"] = dict(Counter(f["panel"] for f in finds))
out["integrity"] = integrity

# ---- 2. every configuration on the full set, with intervals and tie groups
bs_pr: dict = {}
bs = boot(full_cfgs, pr_list, bs_pr)
table = []
for c in full_cfgs:
    p, r, f1, f2 = score(counts(c, pr_list))
    lo, hi = np.percentile(bs[c], [2.5, 97.5])
    rr = [x for x in runs if cfg_key(x) == c]
    unc = sum(float(x["cost_uncached"] or 0) for x in rr)
    tps = counts(c, pr_list)[:, 0].sum()
    table.append({"model": c[0], "tier": c[1], "route": models_tab[c[0]]["route"], "precision": p, "recall": r, "f1": f1, "f2": f2,
                  "f2_lo": float(lo), "f2_hi": float(hi), "tp": int(tps), "fp": int(counts(c, pr_list)[:, 1].sum()),
                  "fn": int(counts(c, pr_list)[:, 2].sum()), "findings_per_pr": statistics.mean(int(x["findings"] or 0) for x in rr),
                  "usd_per_pr": statistics.mean(float(x["cost_list"] or 0) for x in rr), "usd_uncached_per_pr": unc / len(rr),
                  "usd_per_tp": unc / tps if tps else None,
                  "latency_median_s": statistics.median(float(x["latency_s"] or 0) for x in rr),
                  "latency_p90_s": float(np.percentile([float(x["latency_s"] or 0) for x in rr], 90)),
                  "output_tokens_per_pr": statistics.mean(float(x["output"] or 0) for x in rr),
                  "reasoning_per_pr": (statistics.mean(v) if (v := [float(x["reasoning"]) for x in rr if x["reasoning"] not in ("", None)]) else None),
                  "unparseable": sum(1 for x in rr if x["status"] == "parse_error"), "salvaged": sum(1 for x in rr if x.get("salvaged") == "True"),
                  "kappa": float(report_cfg[c]["kappa_golden"]) if report_cfg.get(c) and report_cfg[c]["kappa_golden"] else None})
table.sort(key=lambda t: -t["f2"])
group, groups, head = 1, {}, None
for t in table:                      # a configuration joins the group of the group's leader unless it is significantly worse
    c = (t["model"], t["tier"])
    if head is None:
        head = c
    else:
        diff = bs[head] - bs[c]
        if np.percentile(diff, 2.5) > 0:
            group += 1
            head = c
    groups[c] = group
    t["group"] = group
out["configs"] = table
# F1 view too
out["by_f1"] = sorted(({"model": t["model"], "tier": t["tier"], "f1": t["f1"]} for t in table), key=lambda t: -t["f1"])

# ---- 3. views: vendor default, best tier per model, frontier ten
out["vendor_default"] = [t for t in table if t["tier"] == "default"]
best = {}
for t in table:
    if t["model"] not in best or t["f2"] > best[t["model"]]["f2"]:
        best[t["model"]] = t
out["best_tier"] = sorted(best.values(), key=lambda t: -t["f2"])
fr_prs = sorted(frontier_set)
fr_cfgs = configs
bs_fr = boot(fr_cfgs, fr_prs)
fr = []
for c in fr_cfgs:
    p, r, f1, f2 = score(counts(c, fr_prs))
    lo, hi = np.percentile(bs_fr[c], [2.5, 97.5])
    rr = [x for x in runs if cfg_key(x) == c and x["pr"] in frontier_set]
    fr.append({"model": c[0], "tier": c[1], "precision": p, "recall": r, "f1": f1, "f2": f2, "f2_lo": float(lo), "f2_hi": float(hi),
               "usd_uncached_per_pr": statistics.mean(float(x["cost_uncached"] or 0) for x in rr)})
fr.sort(key=lambda t: -t["f2"])
out["frontier"] = fr

# ---- 4. cost and speed: Pareto frontier on uncached $/PR against F2
pts = sorted(table, key=lambda t: (t["usd_uncached_per_pr"], -t["f2"]))
pareto, best_f2 = [], -1
for t in pts:
    if t["f2"] > best_f2:
        pareto.append((t["model"], t["tier"]))
        best_f2 = t["f2"]
for t in table:
    t["pareto"] = (t["model"], t["tier"]) in pareto
out["pareto"] = pareto

# ---- 5. effort per model
eff = defaultdict(dict)
for t in table:
    eff[t["model"]][t["tier"]] = {k: t[k] for k in ("f2", "f1", "precision", "recall", "usd_uncached_per_pr", "latency_median_s", "output_tokens_per_pr", "findings_per_pr")}
for m, tiers in eff.items():               # each higher tier against low, on the same bootstrap draws (paired)
    for t in ("default", "xhigh"):
        if "low" in tiers and t in tiers:
            d = bs[(m, t)] - bs[(m, "low")]
            lo, hi = np.percentile(d, [2.5, 97.5])
            tiers[f"{t}_minus_low"] = {"f2": tiers[t]["f2"] - tiers["low"]["f2"], "lo": float(lo), "hi": float(hi),
                                        **{k: {"diff": tiers[t][k] - tiers["low"][k],
                                               "lo": float(np.percentile(bs_pr[(m, t)][k] - bs_pr[(m, "low")][k], 2.5)),
                                               "hi": float(np.percentile(bs_pr[(m, t)][k] - bs_pr[(m, "low")][k], 97.5))}
                                           for k in ("recall", "precision")},
                                        "cost_ratio": tiers[t]["usd_uncached_per_pr"] / tiers["low"]["usd_uncached_per_pr"],
                                        "latency_ratio": tiers[t]["latency_median_s"] / tiers["low"]["latency_median_s"]}
out["effort"] = eff

# ---- 6. breakdowns, best tier per model: recall by golden category and severity; F2 by PR dimension
def recall_by(cfg, key):
    hit, tot = Counter(), Counter()
    for g in gres:
        if cfg_key(g) == cfg:
            k = golds[g["golden"]][key] or "?"
            tot[k] += 1
            hit[k] += g["found"] == "True"
    return {k: [hit[k], tot[k]] for k in tot}


def f2_by(cfg, dim):
    vals = defaultdict(list)
    for p, v in prs.items():
        vals[v[dim] or "?"].append(p)
    res = {}
    for k, ps in vals.items():
        _, r, _, f2 = score(counts(cfg, ps))
        res[k] = {"f2": f2, "recall": r, "prs": len(ps)}
    return res


bd = {}
for m, t in best.items():
    c = (m, t["tier"])
    bd[f"{m}/{t['tier']}"] = {"recall_by_category": recall_by(c, "category"), "recall_by_severity": recall_by(c, "severity"),
                              **{f"f2_by_{d}": f2_by(c, d) for d in ("language", "repository", "size", "domain", "change_type", "difficulty", "risk", "context")}}
out["breakdowns"] = bd

# ---- 7. noise: findings per PR against precision; precision by the model's own category (all configurations)
mc = defaultdict(lambda: [0, 0])
for f in finds:
    if f["panel"] in ("false_positive", "matches_golden", "unresolved"):
        k = (f["model_category"] or "?").lower()
        mc[k][0] += 1
        mc[k][1] += f["panel"] == "false_positive"
out["precision_by_model_category"] = {k: {"findings": v[0], "precision": 1 - v[1] / v[0]} for k, v in sorted(mc.items(), key=lambda kv: -kv[1][0])}

# ---- 8. complementarity over the best tier per model (full-set models), core goldens
bests = [(m, t["tier"]) for m, t in best.items()]


def complementarity(fb_map):
    nf = {g: len(fb_map[g] & set(bests)) for g in CORE}
    cv = {c: {g for g in CORE if c in fb_map[g]} for c in bests}
    return nf, cv


per_rep = {r: complementarity(found_by_rep[r]) for r in REPS}
nfound = per_rep[REPS[0]][0]
dist = Counter(nfound.values())
out["complementarity"] = {"core_goldens": len(CORE), "models": len(bests),       # lists: in every repeat; numbers: mean over repeats
                          "found_by_none": sorted(g for g in CORE if all(per_rep[r][0][g] == 0 for r in REPS)),
                          "found_by_all": sorted(g for g in CORE if all(per_rep[r][0][g] == len(bests) for r in REPS)),
                          "distribution": dict(sorted(dist.items())), "distribution_repeat": REPS[0]}
union = set().union(*(found_by_c for found_by_c in []))  # placeholder kept simple below
mean_over = lambda f: statistics.mean(f(per_rep[r][1]) for r in REPS)
best_single = max(bests, key=lambda c: mean_over(lambda cv: len(cv[c])))
cheap = sorted(bests, key=lambda c: next(t["usd_uncached_per_pr"] for t in table if (t["model"], t["tier"]) == c))[:3]
out["complementarity"]["best_single"] = {"config": "/".join(best_single), "core_found": mean_over(lambda cv: len(cv[best_single]))}
out["complementarity"]["union_of_three_cheapest"] = {"configs": ["/".join(c) for c in cheap], "core_found": mean_over(lambda cv: len(set().union(*(cv[c] for c in cheap))))}
out["complementarity"]["union_all"] = mean_over(lambda cv: len(set().union(*cv.values())))
pairs = {}
for a in bests:
    for b in bests:
        if a < b:
            pairs[f"{'/'.join(a)} + {'/'.join(b)}"] = mean_over(lambda cv, a=a, b=b: len(cv[a] | cv[b]))
out["complementarity"]["best_pairs"] = dict(sorted(pairs.items(), key=lambda kv: -kv[1])[:10])

# ---- 9. judge robustness: each judge's own F2 ranking against the panel's (Kendall tau over configurations it judged)
pj = {r["config"]: r for r in rows(REPORT / "per_judge.csv")}
judges = sorted({k[3:] for r in pj.values() for k in r if k.startswith("f2_")})


def kendall(a, b):
    n = len(a)
    s = sum(np.sign(a[i] - a[j]) * np.sign(b[i] - b[j]) for i in range(n) for j in range(i + 1, n))
    return s / (n * (n - 1) / 2) if n > 1 else None


panel = {f"{t['model']}/{t['tier']}": t["f2"] for t in table}
jr = {}
for j in judges:
    cs = [c for c in panel if pj.get(c, {}).get(f"f2_{j}") not in (None, "")]
    jr[j] = {"configs": len(cs), "kendall_tau_vs_panel": kendall([panel[c] for c in cs], [float(pj[c][f"f2_{j}"]) for c in cs]),
             "mean_f2": statistics.mean(float(pj[c][f"f2_{j}"]) for c in cs) if cs else None,
             "panel_mean_f2_same_configs": statistics.mean(panel[c] for c in cs) if cs else None}
out["judges"] = jr
out["kappa"] = {"median": statistics.median(t["kappa"] for t in table if t["kappa"] is not None),
                "min": min(t["kappa"] for t in table if t["kappa"] is not None)}

# ---- 10. repeat stability (several repeats): F2 per repeat, the change between repeats on the same PRs (paired
# bootstrap over PRs), rank correlation between repeats, and whether each configuration keeps its group
if len(REPS) > 1:
    def rep_counts(cfg, rp, prset):
        return np.array([[rep_tp[(cfg, p, rp)], rep_fp[(cfg, p, rp)], rep_fn[(cfg, p, rp)]] for p in prset], dtype=float)

    def f2_of(m):
        t, f_, n = m.sum(axis=0)
        p = t / (t + f_) if t + f_ else 0.0
        r = t / (t + n) if t + n else 0.0
        return fb(p, r, BETA)

    idx = RNG.integers(0, len(pr_list), size=(B, len(pr_list)))
    stab = {}
    for c in full_cfgs:
        mats = [rep_counts(c, rp, pr_list) for rp in REPS]
        f2s = [f2_of(m) for m in mats]
        d = []
        for row in idx:                     # difference between the last and the first repeat, same resampled PRs
            d.append(f2_of(mats[-1][row]) - f2_of(mats[0][row]))
        lo, hi = np.percentile(d, [2.5, 97.5])
        stab[f"{c[0]}/{c[1]}"] = {"f2_by_repeat": dict(zip(REPS, f2s)), "change": f2s[-1] - f2s[0], "change_lo": float(lo), "change_hi": float(hi)}
        boots = []                          # every repeat's F2 on the same resampled PRs, for each pair of repeats
        for m in mats:
            s_ = m[idx].sum(axis=1)
            t_, f_, n_ = s_[:, 0], s_[:, 1], s_[:, 2]
            p_ = np.divide(t_, t_ + f_, out=np.zeros_like(t_), where=(t_ + f_) > 0)
            r_ = np.divide(t_, t_ + n_, out=np.zeros_like(t_), where=(t_ + n_) > 0)
            d_ = BETA * BETA * p_ + r_
            boots.append(np.divide((1 + BETA * BETA) * p_ * r_, d_, out=np.zeros_like(d_), where=d_ > 0))
        prs_ = {}
        for i, a in enumerate(REPS):
            for j in range(i + 1, len(REPS)):
                lo_, hi_ = np.percentile(boots[j] - boots[i], [2.5, 97.5])
                prs_[f"{a}-{REPS[j]}"] = {"change": f2s[j] - f2s[i], "lo": float(lo_), "hi": float(hi_)}
        stab[f"{c[0]}/{c[1]}"]["pairs"] = prs_
        stab[f"{c[0]}/{c[1]}"]["spread"] = max(f2s) - min(f2s)
    changes = [abs(v["change"]) for v in stab.values()]
    names = list(stab)
    taus = {}
    for i, a in enumerate(REPS):
        for b in REPS[i + 1:]:
            taus[f"{a}-{b}"] = kendall([stab[n]["f2_by_repeat"][a] for n in names], [stab[n]["f2_by_repeat"][b] for n in names])
    out["repeat_stability"] = {"configs": stab, "abs_change_median": statistics.median(changes), "abs_change_max": max(changes),
                               "significant_changes": [n for n, v in stab.items() if v["change_lo"] > 0 or v["change_hi"] < 0],
                               "kendall_tau_between_repeats": taus,
                               "pairs": {k: {"abs_change_median": statistics.median(abs(v["pairs"][k]["change"]) for v in stab.values()),
                                             "abs_change_max": max(abs(v["pairs"][k]["change"]) for v in stab.values()),
                                             "significant": [n for n, v in stab.items() if v["pairs"][k]["lo"] > 0 or v["pairs"][k]["hi"] < 0]}
                                         for k in next(iter(stab.values()))["pairs"]},
                               "spread_median": statistics.median(v["spread"] for v in stab.values()),
                               "spread_max": max(v["spread"] for v in stab.values())}

# ---- 11. operations
out["operations"] = {
    "runs": len(runs), "calls": sum(int(r["calls"]) for r in runs), "failed_attempts": sum(int(r["failed_attempts"] or 0) for r in runs),
    "unparseable": [r["run"] for r in runs if r["status"] == "parse_error"],
    "multi_call_runs": sum(1 for r in runs if int(r["calls"]) > 1),
    "tokens_per_char": {m: statistics.median(float(r["prompt_tokens"]) / float(r["prompt_chars"]) for r in runs if r["model"] == m and r["prompt_tokens"])
                        for m in sorted({r["model"] for r in runs})},
    "review_usd_list": sum(float(r["cost_list"] or 0) for r in runs), "review_usd_uncached": sum(float(r["cost_uncached"] or 0) for r in runs),
    "openrouter_billed_reviews": sum(float(r["cost_reported"] or 0) for r in runs),
}
(REPORT / "analysis.json").write_text(json.dumps(out, indent=1, default=lambda o: list(o) if isinstance(o, (set, tuple)) else str(o)))
print(f"written {REPORT / 'analysis.json'}; integrity: {json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in integrity.items()})}")
