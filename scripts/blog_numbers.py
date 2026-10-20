"""Every number in the blog post, from a report's analysis (reports/<report>/analysis.json), its CSVs, the frontier
view's analysis and the judged records, so each sentence of the post can be checked against one command. Repeats are
pooled the way the report pools them (counts summed per configuration and pull request).
Usage: python scripts/blog_numbers.py <report> <repeats, e.g. 1-2>"""
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crbench.metrics import PROFILES, _category, fbeta, golden_lookup

REPORT = ROOT / "reports" / sys.argv[1]
_r = sys.argv[2] if len(sys.argv) > 2 else "1"
REPS = list(range(int(_r.split("-")[0]), int(_r.split("-")[-1]) + 1)) if "-" in _r else [int(x) for x in _r.split(",")]
A = json.loads((REPORT / "analysis.json").read_text())
FA = A    # the analysis of a report built with --frontier holds the frontier view's configurations under "frontier"
NAMES = {"claude-opus-5.5": "Opus 5.5", "claude-sonnet-5.5": "Sonnet 5.5", "claude-opus-5": "Opus 5", "claude-sonnet-5": "Sonnet 5", "claude-haiku-5.5": "Haiku", "claude-fable-5.1": "Fable",
         "gpt-6.1-sol": "Sol", "gpt-5.6-terra": "Terra", "gpt-6-luna": "Luna", "gpt-6-astra": "Astra", "muse-spark-1.3": "Muse Spark", "muse-wonder": "Muse Wonder",
         "deepseek-v4-pro": "DeepSeek", "deepseek-v4.1-flash": "DeepSeek Flash", "qwen3.8-max": "Qwen", "glm-5.3": "GLM", "kimi-k3": "Kimi", "minimax-m3": "MiniMax",
         "gemini-4-argon": "Gemini", "mistral-large-4": "Mistral", "grok-4.7": "Grok"}
LEVEL = {("deepseek-v4-pro", "default"): "high", ("deepseek-v4.1-flash", "default"): "high", ("glm-5.3", "default"): "high", ("gemini-4-argon", "xhigh"): "high",
         ("mistral-large-4", "low"): "no reasoning"}
CONFIGS = A["configs"]
BY = {(c["model"], c["tier"]): c for c in CONFIGS}
pct = lambda v: f"{100 * v:.1f}"
name = lambda m, t: f"{NAMES[m]} {LEVEL.get((m, t), t)}"
cname = lambda c: name(c["model"], c["tier"])


def head(t):
    print(f"\n== {t}")


def csv_rows(name):
    with open(REPORT / name) as f:
        return list(csv.DictReader(f))


head("results: groups")
top = [c for c in CONFIGS if c["group"] == 1]
print(f"group 1: {len(top)} configurations, F2 {pct(min(c['f2'] for c in top))} to {pct(max(c['f2'] for c in top))}")
for g in sorted({c["group"] for c in CONFIGS}):
    print(f"  group {g}: " + ", ".join(f"{cname(c)} {pct(c['f2'])}" for c in sorted(CONFIGS, key=lambda c: -c["f2"]) if c["group"] == g))
lead = max(CONFIGS, key=lambda c: c["f2"])
print(f"leader {cname(lead)}: P {pct(lead['precision'])} R {pct(lead['recall'])} F2 {pct(lead['f2'])}")
print(f"interval half-widths: {min((c['f2_hi'] - c['f2_lo']) / 2 for c in CONFIGS) * 100:.1f} to {max((c['f2_hi'] - c['f2_lo']) / 2 for c in CONFIGS) * 100:.1f}"
      f" (median {statistics.median((c['f2_hi'] - c['f2_lo']) / 2 for c in CONFIGS) * 100:.1f})")

head("results: every configuration (table)")
print("model | level | group | P | R | F1 | F2 | 95% | findings/PR | $/PR | median time")
for c in sorted(CONFIGS, key=lambda c: -c["f2"]):
    t = c["latency_median_s"]
    tt = f"{t:.0f} s" if t < 100 else f"{t / 60:.1f} min"
    print(f"{cname(c)} | {c['group']} | {pct(c['precision'])} | {pct(c['recall'])} | {pct(c['f1'])} | **{pct(c['f2'])}** | "
          f"{100 * c['f2_lo']:.0f}-{100 * c['f2_hi']:.0f} | {c['findings_per_pr']:.1f} | {c['usd_uncached_per_pr']:.3f} | {tt}")

head("results: F1 order, vendor defaults")
print("by F1: " + ", ".join(f"{name(x['model'], x['tier'])} {pct(x['f1'])}" for x in A["by_f1"][:5]))
print(f"Mistral F1 {pct(BY[('mistral-large-4', 'low')]['f1'])}")
print("defaults: " + ", ".join(f"{cname(c)} {pct(c['f2'])}" for c in A["vendor_default"][:6]))
print(f"Gemini default {pct(BY[('gemini-4-argon', 'default')]['f2'])} vs high {pct(BY[('gemini-4-argon', 'xhigh')]['f2'])}")

if FA:
    head(f"results: frontier set (10 PRs, {len(FA['frontier'])} configurations)")
    fr = sorted(FA["frontier"], key=lambda c: -c["f2"])
    for i, c in enumerate(fr, 1):
        if i <= 3 or c["model"] in ("claude-fable-5.1", "gpt-6-astra"):
            print(f"  {i:2d}. {cname(c)} F2 {pct(c['f2'])} P {pct(c['precision'])} R {pct(c['recall'])} ${c['usd_uncached_per_pr']:.3f}/PR")
    print(f"  interval half-widths {min((c['f2_hi'] - c['f2_lo']) / 2 for c in fr) * 100:.0f} to {max((c['f2_hi'] - c['f2_lo']) / 2 for c in fr) * 100:.0f}")

head("raw models and the review tools (the site's 21 tools judged by our panel: scripts/site_products.py, products_vs_models.py)")
best = A["best_tier"]
for th in (64, 62, 60, 58):
    print(f"  F2 >= {th}: {sum(1 for c in best if c['f2'] * 100 >= th)} models at their best level, {sum(1 for c in CONFIGS if c['f2'] * 100 >= th)} configurations")
PV = ROOT / "reports" / "products" / f"vs-{sys.argv[1]}.json"
if PV.exists():
    T = json.loads(PV.read_text())["table"]
    tools = [t for t in T if t["kind"] == "product"]
    mods = [t for t in T if t["kind"] == "model"]
    SITE_J = {"anthropic_claude-opus-4-5-20251101": "Opus 4.5", "anthropic_claude-sonnet-4-5-20250929": "Sonnet 4.5", "openai_gpt-5.2": "GPT-5.2"}
    print("tool | reviewed | findings/PR | P | R | F1 | F2 | 95% | group | site F2 (Opus 4.5 default)")
    for t in tools:
        print(f"{t['name']} | {t['review_dates'][0][:7]} | {t['findings_per_pr']:.1f} | {pct(t['precision'])} | {pct(t['recall'])} | {pct(t['f1'])} | "
              f"**{pct(t['f2'])}** | {pct(t['f2_lo'])}-{pct(t['f2_hi'])} | {t['group']} | {pct(t['site_f2']['anthropic_claude-opus-4-5-20251101'])}")
    # the ten best, raw models (each at its best level for that measure) and tools together
    for metric, title in (("f2", "F2"), ("f1", "F1")):
        best_m = {}
        for t in mods:
            if t["model"] not in best_m or t[metric] > best_m[t["model"]][metric]:
                best_m[t["model"]] = t
        both = [(name(t["model"], t["tier"]), "raw model", t) for t in best_m.values()] + [(t["name"], "review tool", t) for t in tools]
        both.sort(key=lambda r: -r[2][metric])
        print(f"top 10 by {title} | type | P | R | F1 | F2")
        for i, (nm, kind, t) in enumerate(both[:10], 1):
            print(f"{i} | {nm} | {kind} | {pct(t['precision'])} | {pct(t['recall'])} | {pct(t['f1'])} | {pct(t['f2'])}")
        print("  just outside: " + ", ".join(f"{nm} {pct(t[metric])}" for nm, _, t in both[10:13]))
    g1 = [t for t in T if t["group"] == 1]
    print(f"top group of the joint ranking: {len(g1)} rows, {sum(1 for t in g1 if t['kind'] == 'model')} configurations + "
          f"{', '.join(t['name'] for t in g1 if t['kind'] == 'product')}; F2 {pct(min(t['f2'] for t in g1))} to {pct(max(t['f2'] for t in g1))}")
    bp = tools[0]
    lead = T[0]
    print(f"best tool {bp['name']} F2 {pct(bp['f2'])}; leader {lead['name']} {pct(lead['f2'])}, "
          f"{100 * lead['vs_best_product']['diff']:+.1f} ({100 * lead['vs_best_product']['lo']:+.1f} to {100 * lead['vs_best_product']['hi']:+.1f})")
    above = [t for t in mods if t["f2"] > bp["f2"]]
    print(f"configurations above the best tool: {len(above)} ({', '.join(t['name'] for t in above)}); "
          f"significantly above: {sum(1 for t in mods if t['vs_best_product']['lo'] > 0)}")
    print("tools in each group: " + ", ".join(f"G{g} {sum(1 for t in tools if t['group'] == g)}" for g in sorted({t['group'] for t in tools})))
    med = lambda xs: statistics.median(xs)
    print(f"median precision tools {pct(med([t['precision'] for t in tools]))} vs configurations {pct(med([t['precision'] for t in mods]))}; "
          f"recall {pct(med([t['recall'] for t in tools]))} vs {pct(med([t['recall'] for t in mods]))}; "
          f"findings/PR tools {med([t['findings_per_pr'] for t in tools]):.1f} vs configurations {med([c['findings_per_pr'] for c in CONFIGS]):.1f}")
    top3 = tools[:3]
    print(f"best three tools: P {pct(min(t['precision'] for t in top3))}-{pct(max(t['precision'] for t in top3))}, "
          f"R {pct(min(t['recall'] for t in top3))}-{pct(max(t['recall'] for t in top3))}, findings/PR {min(t['findings_per_pr'] for t in top3):.1f}-{max(t['findings_per_pr'] for t in top3):.1f}")
    print("by F1: " + ", ".join(f"{t['name']} {pct(t['f1'])}" for t in sorted(T, key=lambda t: -t["f1"])[:6]))
    for jm, jn in SITE_J.items():
        xs = [t for t in tools if jm in t["site_f2"]]
        d = [100 * (t["f2"] - t["site_f2"][jm]) for t in xs]
        pairs = [(a["f2"] - b["f2"]) * (a["site_f2"][jm] - b["site_f2"][jm]) for i, a in enumerate(xs) for b in xs[i + 1:]]
        tau = (sum(x > 0 for x in pairs) - sum(x < 0 for x in pairs)) / sum(x != 0 for x in pairs)
        print(f"our panel - site's {jn}: mean {statistics.mean(d):+.1f}, {min(d):+.1f} to {max(d):+.1f} ({len(xs)} tools), Kendall tau of the order {tau:.2f}")
    grp = {(c["model"], c["tier"]): c["group"] for c in CONFIGS}
    print(f"model rows whose group changes in the joint ranking: {sum(1 for t in mods if t['group'] != grp[(t['model'], t['tier'])])}")
    dates = sorted(d for t in tools for d in t["review_dates"])
    print(f"tool reviews ran {dates[0]} to {dates[-1]}")
    S = json.loads((ROOT / "results" / "products" / "summary.json").read_text())
    print("each judge alone (F2, best three tools): " + "; ".join(f"{t['name']}: " + ", ".join(f"{j} {pct(v)}" for j, v in S[t['tool']]["our_judges_alone_f2"].items()) for t in top3))

head("cost and speed")
print("pareto: " + ", ".join(name(m, t) for m, t in A["pareto"]))
cheap_top = min(top, key=lambda c: c["usd_uncached_per_pr"])
print(f"cheapest in group 1: {cname(cheap_top)} ${cheap_top['usd_uncached_per_pr']:.3f} F2 {pct(cheap_top['f2'])}")
for c in sorted(top, key=lambda c: c["usd_uncached_per_pr"]):
    print(f"  {cname(c)}: {c['usd_uncached_per_pr'] / cheap_top['usd_uncached_per_pr']:.1f}x the cost, {100 * (c['f2'] - cheap_top['f2']):+.1f} F2, "
          f"${c['usd_per_tp']:.3f} per TP")
print("cheapest per TP overall: " + ", ".join(f"{cname(c)} ${c['usd_per_tp']:.3f}" for c in sorted(CONFIGS, key=lambda c: c["usd_per_tp"])[:6]))
print("fastest: " + ", ".join(f"{cname(c)} {c['latency_median_s']:.1f} s" for c in sorted(CONFIGS, key=lambda c: c["latency_median_s"])[:5]))
print("slowest: " + ", ".join(f"{cname(c)} {c['latency_median_s'] / 60:.1f} min (p90 {c['latency_p90_s'] / 60:.0f}), {c['output_tokens_per_pr']:,.0f} out/PR"
                              for c in sorted(CONFIGS, key=lambda c: -c["latency_median_s"])[:4]))
fr_cost = sum(c["usd_uncached_per_pr"] for c in (FA["frontier"] if FA else []) if c["model"] in ("claude-fable-5.1", "gpt-6-astra")) * 10
print(f"reviews per pass at list price (uncached): full ${sum(c['usd_uncached_per_pr'] for c in CONFIGS) * 50:.0f}"
      f" + frontier-only models ${fr_cost:.0f}")

head("effort")
gain, flat, border = [], [], []
cost_r, lat_r = [], []
for m, e in sorted(A["effort"].items()):
    deltas = {k: v for k, v in e.items() if k.endswith("_minus_low")}
    if not deltas:
        continue
    sig = [k for k, v in deltas.items() if v["lo"] > 0]
    (gain if sig else flat).append(m)
    top_tier = "xhigh" if "xhigh_minus_low" in deltas else "default"
    d = deltas[f"{top_tier}_minus_low"]
    cost_r.append(d["cost_ratio"])
    lat_r.append(d["latency_ratio"])
    if not sig and d["f2"] > 0.03:
        border.append(m)
    print(f"  {NAMES[m]:9s} " + "  ".join(f"{k.split('_')[0]} {100 * v['f2']:+.1f} [{100 * v['lo']:+.1f},{100 * v['hi']:+.1f}] cost x{v['cost_ratio']:.1f} time x{v['latency_ratio']:.1f}"
                                         for k, v in deltas.items()))
print(f"models with more than one level: {len(gain) + len(flat)}; significant gain: {[NAMES[m] for m in gain]}; borderline: {[NAMES[m] for m in border]}")
print(f"highest vs low: cost x{min(cost_r):.1f} to x{max(cost_r):.1f}; time x{min(lat_r):.1f} to x{max(lat_r):.1f} (sorted: {sorted(round(x, 1) for x in lat_r)})")
for m in ("claude-sonnet-5.5", "claude-opus-5.5", "gpt-5.6-terra", "gpt-6-luna"):
    lo, hi = A["effort"][m]["low"], A["effort"][m]["xhigh"]
    print(f"  {NAMES[m]} low -> xhigh: findings {lo['findings_per_pr']:.1f} -> {hi['findings_per_pr']:.1f}, recall {pct(lo['recall'])} -> {pct(hi['recall'])}, "
          f"precision {pct(lo['precision'])} -> {pct(hi['precision'])}")

head("effort: recall and precision against low (paired bootstrap; * = the 95% interval leaves out zero)")
sig_ = lambda d: d["lo"] > 0 or d["hi"] < 0
top_models = {c["model"] for c in CONFIGS if c["group"] == 1}
up, down, held = [], [], []
print("model | level | R | R vs low | P | P vs low | F2 vs low | findings/PR (low)")
for m, e in sorted(A["effort"].items(), key=lambda kv: -max(v["f2"] for k, v in kv[1].items() if "_minus_" not in k)):
    if "low" not in e or not any(k.endswith("_minus_low") for k in e):
        continue
    for k in ("default", "xhigh"):
        d = e.get(f"{k}_minus_low")
        if d:
            mark = lambda x: f"{100 * x['diff']:+.1f}{'*' if sig_(x) else ''}"
            print(f"{name(m, k)} | {pct(e[k]['recall'])} | {mark(d['recall'])} | {pct(e[k]['precision'])} | {mark(d['precision'])} | "
                  f"{100 * d['f2']:+.1f}{'*' if sig_(d) else ''} | {e[k]['findings_per_pr']:.1f} ({e['low']['findings_per_pr']:.1f})")
    hk = "xhigh" if "xhigh_minus_low" in e else "default"           # the highest level against low
    r, pr = e[f"{hk}_minus_low"]["recall"], e[f"{hk}_minus_low"]["precision"]
    (up if sig_(r) and r["diff"] > 0 else held).append((m, r["diff"]))
    if sig_(pr) and pr["diff"] < 0:
        down.append((m, pr["diff"]))
fmt = lambda xs: ", ".join(f"{NAMES[m]} {100 * v:+.1f}" for m, v in sorted(xs, key=lambda x: x[1]))
print(f"highest level: recall up significantly for {len(up)}: {fmt(up)}; not significantly for {len(held)}: {fmt(held)}")
print(f"highest level: precision down significantly for {len(down)}: {fmt(down)}; the others: "
      + fmt([(m, A["effort"][m][("xhigh" if "xhigh_minus_low" in A["effort"][m] else "default") + "_minus_low"]["precision"]["diff"])
             for m in A["effort"] if m not in {x for x, _ in down} and "low" in A["effort"][m] and len(A["effort"][m]) > 1]))
for m in sorted(top_models):
    e = A["effort"][m]
    print(f"  top group {NAMES[m]} xhigh vs low: findings {e['low']['findings_per_pr']:.2f} -> {e['xhigh']['findings_per_pr']:.2f}, "
          f"recall {100 * e['xhigh_minus_low']['recall']['diff']:+.1f}, precision {100 * e['xhigh_minus_low']['precision']['diff']:+.1f}")
most = max(CONFIGS, key=lambda c: c["recall"])
print(f"highest recall of any configuration: {cname(most)} {pct(most['recall'])} at precision {pct(most['precision'])}")

head("precision and volume")
few = [c for c in CONFIGS if c["findings_per_pr"] < 3.5]
many = [c for c in CONFIGS if c["findings_per_pr"] > 6.5]
for lab, g in (("< 3.5", few), ("> 6.5", many)):
    print(f"findings {lab}: {len(g)} configurations, mean precision {pct(statistics.mean(c['precision'] for c in g))}, mean recall {pct(statistics.mean(c['recall'] for c in g))}: "
          + ", ".join(cname(c) for c in g))
for c in sorted(top, key=lambda c: c["findings_per_pr"])[:6]:
    print(f"  {cname(c)}: {c['findings_per_pr']:.1f} findings, P {pct(c['precision'])}, R {pct(c['recall'])}")
mi = BY[("mistral-large-4", "low")]
print(f"Mistral: {mi['findings_per_pr']:.1f} findings, P {pct(mi['precision'])}")

head("what models find and miss (pooled counts; per pass = divide by the number of repeats)")
n = len(REPS)
cat = csv_rows("recall_by_category.csv")
sev = csv_rows("recall_by_severity.csv")
for c in best:
    k = f"{c['model']}/{c['tier']}"
    s = {r["category"]: r for r in cat if r["config"] == k}
    v = {r["severity"]: r for r in sev if r["config"] == k}
    f = lambda r: f"{int(r['tp']) / n:.1f}/{int(r['goldens']) // n} ({100 * float(r['recall']):.0f}%)" if r else "-"
    print(f"  {cname(c):22s} security {f(s.get('security'))}  concurrency {f(s.get('concurrency'))}  critical {f(v.get('Critical'))}  low {f(v.get('Low'))}")
sl = csv_rows("slices.csv")
for c in best[:6]:
    k = f"{c['model']}/{c['tier']}"
    size = {r["value"]: r for r in sl if r["config"] == k and r["dimension"] == "pr_size_category"}
    print(f"  {cname(c)} by size: " + ", ".join(f"{s} {100 * float(size[s]['fbeta']):.0f} ({size[s]['prs']} PRs)" for s in ("small", "medium", "large") if s in size))
for c in best:
    k = f"{c['model']}/{c['tier']}"
    b = A["breakdowns"].get(k, {})
    langs = {l: x["f2"] for l, x in b.get("f2_by_language", {}).items()}
    if langs and max(langs.values()) - min(langs.values()) >= 0.10:
        print(f"  {cname(c)} language spread {100 * (max(langs.values()) - min(langs.values())):.0f}: " + ", ".join(f"{l} {100 * v:.0f}" for l, v in sorted(langs.items(), key=lambda kv: kv[1])))
cm = A["complementarity"]
print(f"complementarity ({cm['models']} models at their best level, {cm['core_goldens']} core goldens, averaged over repeats): union {cm['union_all']}, "
      f"found by all in every repeat {len(cm['found_by_all'])}, by none in every repeat {len(cm['found_by_none'])}: {cm['found_by_none']}")
print(f"  best single {cm['best_single']}; three cheapest {cm['union_of_three_cheapest']}")
lead_k = f"{best[0]['model']}/{best[0]['tier']}"
print(f"  {lead_k} alone: {best[0]['tp'] / n:.1f} core goldens per pass; pairs with it: " + ", ".join(f"{k} {v}" for k, v in cm["best_pairs"].items() if lead_k in k))
print("  best pairs: " + ", ".join(f"{k} {v}" for k, v in list(cm["best_pairs"].items())[:5]))
L0, core0 = golden_lookup(), PROFILES["core"]


def found(model, tier, rep):
    d = json.loads((ROOT / "results" / "judged" / f"{model}__{tier}__r{rep}.json").read_text())
    return {(url, x["golden_comment"]) for url, row in d["voted"].items() if not row.get("incomplete")
            for x in row["true_positives"] if _category(x, L0) in core0}


fs = {(c["model"], c["tier"]): {rep: found(c["model"], c["tier"], rep) for rep in REPS} for c in best}
lk = (best[0]["model"], best[0]["tier"])
print(f"  {name(*lk)} with each top-group model at its best level (mean over repeats): " + ", ".join(
    f"{name(*k)} {statistics.mean(len(fs[lk][r] | fs[k][r]) for r in REPS):.1f}" for k in fs if k != lk and BY[k]["group"] == 1))

head("can you trust the judge")
print(f"kappa median {A['kappa']['median']:.2f}, lowest {A['kappa']['min']:.2f}")
pv = A["integrity"]["panel_verdicts"]
print(f"panel verdicts on findings: {pv} (unresolved {100 * pv['unresolved'] / sum(pv.values()):.1f}%)")
print("tau vs panel: " + ", ".join(f"{NAMES[j]} {v['kendall_tau_vs_panel']:.2f} (mean F2 {pct(v['mean_f2'])} vs panel {pct(v['panel_mean_f2_same_configs'])})" for j, v in A["judges"].items()))
pj = {r["config"]: r for r in csv_rows("per_judge.csv")}
for c in best[:2]:
    k = f"{c['model']}/{c['tier']}"
    row = {kk.removeprefix("f2_"): float(v) for kk, v in pj[k].items() if kk.startswith("f2_") and v}
    ranks = {j: 1 + sum(1 for r in pj.values() if r.get(f"f2_{j}") and float(r[f"f2_{j}"]) > v) for j, v in row.items()}
    print(f"  {cname(c)} under each judge: " + ", ".join(f"{NAMES[j]} {100 * v:.1f} (rank {ranks[j]})" for j, v in row.items()))

L, cats = golden_lookup(), PROFILES["core"]
strict = {}
for c in CONFIGS:
    tp = tpu = fp = fn = 0
    for rep in REPS:
        p = ROOT / "results" / "judged" / f"{c['model']}__{c['tier']}__r{rep}.json"
        d = json.loads(p.read_text())
        for row in d["voted"].values():
            if row.get("incomplete"):
                continue
            tps = [x for x in row["true_positives"] if _category(x, L) in cats]
            tp += len(tps)
            tpu += sum(1 for x in tps if len(x.get("judges_yes") or []) == len(d["judges"]))
            fp += row["fp"]
            fn += sum(1 for x in row["false_negatives"] if _category(x, L) in cats)
    P = lambda a, b: a / (a + b) if a + b else 0.0
    strict[(c["model"], c["tier"])] = (fbeta(P(tp, fp), P(tp, fn), 2), fbeta(P(tpu, fp), P(tpu, fn + tp - tpu), 2), tp, tpu)
share = sum(v[3] for v in strict.values()) / sum(v[2] for v in strict.values())
drop = statistics.median((v[0] - v[1]) * 100 for v in strict.values())
keys = list(strict)
conc = sum(1 if (strict[a][0] - strict[b][0]) * (strict[a][1] - strict[b][1]) > 0 else -1 if (strict[a][0] - strict[b][0]) * (strict[a][1] - strict[b][1]) < 0 else 0
           for i, a in enumerate(keys) for b in keys[i + 1:])
tau = conc / (len(keys) * (len(keys) - 1) / 2)
print(f"unanimous share of goldens found {100 * share:.1f}%; unanimous only: median F2 drop {drop:.1f}, tau vs panel {tau:.2f}; top: "
      + ", ".join(f"{name(m, t)} {100 * v[1]:.1f}" for (m, t), v in sorted(strict.items(), key=lambda kv: -kv[1][1])[:5]))

head("operations")
op = A["operations"]
print(f"runs {op['runs']}, calls {op['calls']}, failed attempts {op['failed_attempts']}, multi-call runs {op['multi_call_runs']}, unparseable {op['unparseable']}")
print(f"salvaged {A['integrity']['salvaged']}, statuses {A['integrity']['statuses']}")

if "repeat_stability" in A:
    head("stability between repeats")
    rs = A["repeat_stability"]
    print(f"configurations {len(rs['configs'])}; |change| median {100 * rs['abs_change_median']:.1f}, max {100 * rs['abs_change_max']:.1f}; "
          f"significant {rs['significant_changes']}; tau between repeats {rs['kendall_tau_between_repeats']}")
    ch = sorted(rs["configs"].items(), key=lambda kv: -abs(kv[1]["change"]))
    for k, v in ch[:8]:
        print(f"  {k}: " + " -> ".join(pct(x) for x in v["f2_by_repeat"].values()) + f" ({100 * v['change']:+.1f} [{100 * v['change_lo']:+.1f},{100 * v['change_hi']:+.1f}])")
    within = sum(1 for v in rs["configs"].values() if abs(v["change"]) <= 0.03)
    print(f"  within 3 points: {within} of {len(rs['configs'])}")

head("prompt control: the neutral prompt (one run) against our prompt, per pass and pooled; paired bootstrap over PRs, 4,000 draws")
import random

from crbench.metrics import per_pr_counts


def counts_of(path):
    return per_pr_counts(json.loads(Path(path).read_text())["voted"], "core", L)


def f2_of(cs, urls):
    tp = sum(cs[u][0] for u in urls if u in cs)
    fp = sum(cs[u][1] for u in urls if u in cs)
    fn = sum(cs[u][2] for u in urls if u in cs)
    P = tp / (tp + fp) if tp + fp else 0.0
    R = tp / (tp + fn) if tp + fn else 0.0
    return fbeta(P, R, 2)


def pooled(paths):
    out = {}
    for p in paths:
        for u, c in counts_of(p).items():
            out[u] = tuple(a + b for a, b in zip(out.get(u, (0, 0, 0)), c))
    return out


ctrl = json.loads((ROOT / "results" / "control" / "summary.json").read_text())
for mt in ctrl:
    m, t = mt.split("/")
    neutral = counts_of(ROOT / "results" / "control" / "judged" / f"control-{m}__{t}__r1.json")
    ours = {f"pass {r}": pooled([ROOT / "results" / "judged" / f"{m}__{t}__r{r}.json"]) for r in REPS}
    ours["pooled"] = pooled([ROOT / "results" / "judged" / f"{m}__{t}__r{r}.json" for r in REPS])
    urls = sorted(neutral)
    rng = random.Random(7)
    draws = [[rng.choice(urls) for _ in urls] for _ in range(4000)]
    parts = []
    for k, cs in ours.items():
        d = f2_of(neutral, urls) - f2_of(cs, urls)
        ds = sorted(f2_of(neutral, s) - f2_of(cs, s) for s in draws)
        parts.append(f"{k} {100 * f2_of(cs, urls):.1f} (neutral {100 * d:+.1f} [{100 * ds[100]:+.1f},{100 * ds[3899]:+.1f}])")
    print(f"  {name(m, t)}: neutral {100 * f2_of(neutral, urls):.1f}; " + "; ".join(parts))
