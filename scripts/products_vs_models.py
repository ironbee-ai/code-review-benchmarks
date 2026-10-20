"""The site's 21 products (judged by our panel, scripts/site_products.py) and our full-set configurations in one
ranking: F2 (core profile) with paired-bootstrap intervals over the 50 pull requests (4,000 draws, seed 7, as in
scripts/analyze.py) and tie groups by the same rule (a row joins its group's leader unless significantly worse).
Models pool their repeats per PR (the average of the passes); a product's comments are fixed, judged once.
Usage: python scripts/products_vs_models.py <models report, e.g. full-r123> <repeats, e.g. 1-3>"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import site_products as SP

from crbench.metrics import golden_lookup, per_pr_counts

BETA, B = 2.0, 4000
REPORT = ROOT / "reports" / sys.argv[1]
a, _, b = sys.argv[2].partition("-")
REPS = [str(x) for x in range(int(a), int(b or a) + 1)]
lookup = golden_lookup()
names = SP.read_json(SP.DASHBOARD)["tool_display_names"] | {"copilot-v2": "GitHub Copilot"}
site = SP.site_scores()
rows = {}                                              # name -> {url: [tp, fp, fn]}
kind, extra = {}, {}
bd = SP.read_json(SP.M / "results" / "benchmark_data.json")
dates = {}                                             # each tool's review date (the repositories' suffix)
for v in bd.values():
    for r in v["reviews"]:
        dates.setdefault(r["tool"], set()).add(r["repo_name"].split("__")[-1])
dates[SP.FETCHED] = {v["repo_name"].split("__")[-1] for v in SP.read_json(SP.OUT / SP.FETCHED / "reviews.json").values()}
with open(REPORT / "configs.csv") as f:
    configs = list(csv.DictReader(f))
for c in configs:
    key = f"{c['model']} {c['tier']}"
    acc = {}
    for r in REPS:
        rec = SP.read_json(ROOT / "results" / "judged" / f"{c['model']}__{c['tier']}__r{r}.json")
        for u, v in per_pr_counts(rec["voted"], "core", lookup).items():
            acc[u] = [x + y for x, y in zip(acc.get(u, [0, 0, 0]), v)]
    rows[key], kind[key] = acc, "model"
    extra[key] = {"model": c["model"], "tier": c["tier"]}
    t = np.array(list(acc.values())).sum(axis=0)
    f2 = (1 + BETA ** 2) * t[0] / ((1 + BETA ** 2) * t[0] + BETA ** 2 * t[2] + t[1])
    assert abs(f2 - float(c["f2"])) < 1e-9, (key, f2, c["f2"])          # same numbers as the report
for t in SP.TOOLS:
    rec = SP.read_json(SP.OUT / "judged" / f"site-{t}__default__r1.json")
    rows[names.get(t, t)], kind[names.get(t, t)] = {u: list(v) for u, v in per_pr_counts(rec["voted"], "core", lookup).items()}, "product"
    d = sorted(dates[t])
    extra[names.get(t, t)] = {"tool": t, "review_dates": [f"{x[:4]}-{x[4:6]}-{x[6:]}" for x in d]}
urls = sorted(set.intersection(*(set(v) for v in rows.values())))
assert len(urls) == 50
mat = {k: np.array([v[u] for u in urls], dtype=float) for k, v in rows.items()}
idx = np.random.default_rng(7).integers(0, 50, size=(B, 50))


def f2_of(s):
    t, f, n = s[..., 0], s[..., 1], s[..., 2]
    p = np.divide(t, t + f, out=np.zeros_like(t), where=(t + f) > 0)
    r = np.divide(t, t + n, out=np.zeros_like(t), where=(t + n) > 0)
    d = BETA ** 2 * p + r
    return np.divide((1 + BETA ** 2) * p * r, d, out=np.zeros_like(d), where=d > 0), p, r


bs = {k: f2_of(m[idx].sum(axis=1))[0] for k, m in mat.items()}
table = []
for k, m in mat.items():
    f2, p, r = (float(x) for x in f2_of(m.sum(axis=0)))
    lo, hi = np.percentile(bs[k], [2.5, 97.5])
    table.append({"name": k, "kind": kind[k], "precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0, "f2": f2,
                  "f2_lo": float(lo), "f2_hi": float(hi), "tp": int(m[:, 0].sum()), "fp": int(m[:, 1].sum()), "fn": int(m[:, 2].sum())})
table.sort(key=lambda t: -t["f2"])
group, head = 1, None
for t in table:
    if head is not None and np.percentile(bs[head] - bs[t["name"]], 2.5) > 0:
        group, head = group + 1, t["name"]
    head = head or t["name"]
    t["group"] = group
best_p = next(t for t in table if t["kind"] == "product")
for t in table:
    d = bs[t["name"]] - bs[best_p["name"]]
    t["vs_best_product"] = {"diff": t["f2"] - best_p["f2"], "lo": float(np.percentile(d, 2.5)), "hi": float(np.percentile(d, 97.5))}
theirs = SP.read_json(SP.M / "results" / SP.SITE_JUDGE / "candidates.json")
fetched = SP.read_json(SP.OUT / SP.FETCHED / "candidates.json")
for t in table:
    t.update(extra[t["name"]])
    if t["kind"] == "product":
        tool = t["tool"]
        t["site_f2"] = {jm: SP.site_scores_f2(c[tool]) for jm, c in site.items() if tool in c}
        cands = fetched if tool == SP.FETCHED else theirs
        t["findings_per_pr"] = sum(len((cands.get(u) or {}).get(tool) or []) for u in urls) / 50
out = {"models_report": sys.argv[1], "repeats": REPS, "table": table}
(ROOT / "reports" / "products").mkdir(parents=True, exist_ok=True)
(ROOT / "reports" / "products" / f"vs-{sys.argv[1]}.json").write_text(json.dumps(out, indent=1))
for i, t in enumerate(table, 1):
    v = t["vs_best_product"]
    sig = "*" if v["lo"] > 0 or v["hi"] < 0 else " "
    site_ = "  site " + " / ".join(f"{100 * x:.1f}" for x in t.get("site_f2", {}).values()) if t["kind"] == "product" else ""
    print(f"{i:2d} G{t['group']} {'P' if t['kind'] == 'product' else 'M'} {t['name']:26s} F2 {100 * t['f2']:5.1f} [{100 * t['f2_lo']:4.1f}-{100 * t['f2_hi']:4.1f}] "
          f"P {100 * t['precision']:5.1f} R {100 * t['recall']:5.1f} F1 {100 * t['f1']:5.1f} | vs best product {100 * v['diff']:+5.1f} [{100 * v['lo']:+5.1f},{100 * v['hi']:+5.1f}]{sig}{site_}")
