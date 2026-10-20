"""The report of a set: one row per configuration (model, tier) with its repeats pooled, and the views and slices the
write-up needs. Writes reports/<set>/report.md and CSV files beside it."""
from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

from .config import Model, configs_for, tier_skip, tool_name
from .dataset import load_set
from .env import ROOT
from .judge import load_judged
from .metrics import (
    PROFILES,
    fbeta,
    golden_lookup,
    per_pr_counts,
    pr_labels,
    precision_by_category,
    recall_by,
    score,
    score_counts,
    usage_summary,
)
from .runner import runs_of
from .vote import fleiss_kappa

REPORTS = ROOT / "reports"


def _pct(x) -> str:
    return "" if x is None else f"{100 * x:.1f}"


def _usd(x) -> str:
    return "" if x is None else (f"{x:.4f}" if x < 0.1 else f"{x:.2f}")


def _num(x, d=0) -> str:
    return "" if x is None else f"{x:,.{d}f}"


def pooled(voteds: list[dict]) -> dict:
    """Repeats pooled into one voted map keyed "<url>#<repeat>", so counts and bootstrap intervals cover every repeat."""
    return {f"{url}#{i}": row for i, v in enumerate(voteds) for url, row in v.items()}


def _url_of(key: str) -> str:
    return key.rsplit("#", 1)[0]


def collect(models: list[Model], tiers: list[str], set_name: str, repeats: list[int], pricing: dict, prs: set[str] | None = None) -> list[dict]:
    entries = [e for e in load_set(ROOT / "data" / "sets" / f"{set_name}.json") if not prs or e["id"] in prs]
    urls = {e["golden_url"] for e in entries}
    rows = []
    for model, tier in configs_for(models, tiers, set_name):
        voteds, runs, judged = [], [], []
        reps_judged = []
        for rep in repeats:
            rec = load_judged(tool_name(model.id, tier, rep))
            if rec is None:
                continue
            reps_judged.append(rep)
            keep = lambda rows: {u: r for u, r in rows.items() if u in urls}  # the record covers every PR judged so far
            rec = {**rec, "voted": keep(rec["voted"]), "per_judge": {j: keep(rows) for j, rows in rec["per_judge"].items()},
                   "per_observer": {j: keep(rows) for j, rows in (rec.get("per_observer") or {}).items()}}
            judged.append(rec)
            voteds.append(rec["voted"])
        for r in runs_of(model.id, tier):
            if r and r.get("pr_id") and r.get("golden_url") in urls and r.get("repeat") in repeats:
                runs.append(r)
        rows.append({"model": model, "tier": tier, "voteds": voteds, "judged": judged, "runs": runs, "reps": reps_judged,
                     "usage": usage_summary(runs, pricing.get(model.id))})
    return rows


def config_scores(row: dict, profile: str, beta: float, lookup: dict, urls: set[str] | None = None) -> dict | None:
    if not row["voteds"]:
        return None
    pool = pooled(row["voteds"])
    if urls is not None:
        pool = {k: v for k, v in pool.items() if _url_of(k) in urls}
    s = score(pool, profile, beta, lookup)
    per_rep = []
    for v in row["voteds"]:
        vv = {u: r for u, r in v.items() if urls is None or u in urls}
        c = score_counts(per_pr_counts(vv, profile, lookup), beta)
        per_rep.append(c)
    s["f1_sd"] = statistics.stdev([c["f1"] for c in per_rep]) if len(per_rep) > 1 else None
    s["fbeta_sd"] = statistics.stdev([c["fbeta"] for c in per_rep]) if len(per_rep) > 1 else None
    s["repeats"] = len(per_rep)
    s["incomplete"] = sum(1 for v in row["voteds"] for r in v.values() if r.get("incomplete"))
    return s


def agreement(row: dict) -> dict:
    items_g, items_c = [], []
    for v in row["voteds"]:
        for r in v.values():
            if r.get("incomplete"):
                continue
            items_g.extend(tuple(x) for x in r["agreement"]["golden_items"])
            items_c.extend(tuple(x) for x in r["agreement"]["candidate_items"])
    unanimous = lambda items: (sum(1 for y, n in items if y in (0, n)) / len(items)) if items else None
    return {"kappa_golden": fleiss_kappa(items_g), "kappa_candidate": fleiss_kappa(items_c),
            "unanimous_golden": unanimous(items_g), "unanimous_candidate": unanimous(items_c), "split_golden": sum(1 for y, n in items_g if y not in (0, n))}


def per_judge_scores(row: dict, profile: str, beta: float, lookup: dict) -> dict[str, float]:
    """Each judge's own F-beta for the configuration (the benchmark's single-judge score), to show judge sensitivity."""
    cats = PROFILES[profile]
    out: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for rec in row["judged"]:
        both = {**rec["per_judge"], **{f"{jid} (observer)": rows for jid, rows in (rec.get("per_observer") or {}).items()}}
        for jid, rows in both.items():
            for r in rows.values():
                if not r or r.get("skipped"):
                    continue
                tp = sum(1 for x in r.get("true_positives", []) if (x.get("category") or lookup.get(x.get("golden_comment", ""), {}).get("category")) in cats)
                fn = sum(1 for x in r.get("false_negatives", []) if (x.get("category") or lookup.get(x.get("golden_comment", ""), {}).get("category")) in cats)
                out[jid].append((tp, r.get("fp", 0), fn))
    res = {}
    for jid, counts in out.items():
        tp, fp, fn = (sum(c[i] for c in counts) for i in range(3))
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        res[jid] = fbeta(p, r, beta)
    return res


def observer_agreement(row: dict) -> dict[str, float]:
    """For each observer: the share of golden comments on which it reached the panel's majority verdict (found or not)."""
    same: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    for rec in row["judged"]:
        for url, voted in rec["voted"].items():
            if voted.get("incomplete"):
                continue
            panel_tp = {x["golden_comment"] for x in voted["true_positives"]}
            goldens = panel_tp | {x["golden_comment"] for x in voted["false_negatives"]}
            for jid, rows in (rec.get("per_observer") or {}).items():
                r = rows.get(url)
                if not r or r.get("errors_count", 0) > 0:
                    continue
                obs_tp = {x.get("golden_comment") for x in r.get("true_positives", [])}
                for g in goldens:
                    total[jid] += 1
                    same[jid] += (g in panel_tp) == (g in obs_tp)
    return {jid: same[jid] / total[jid] for jid in total if total[jid]}


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def build(models: list[Model], tiers: list[str], set_name: str, repeats: list[int], pricing: dict, profile: str = "core", beta: float = 2.0,
          sort_key: str = "f1", prs: set[str] | None = None, name: str | None = None) -> Path:
    lookup = golden_lookup()
    labels = pr_labels()
    entries = [e for e in load_set(ROOT / "data" / "sets" / f"{set_name}.json") if not prs or e["id"] in prs]
    index = {e["golden_url"]: e for e in entries}
    rows = collect(models, tiers, set_name, repeats, pricing, prs)
    out_dir = REPORTS / (name or (set_name if not prs else f"{set_name}-{'+'.join(sorted(prs))}"[:120]))
    out_dir.mkdir(parents=True, exist_ok=True)
    # what the report covers, for anyone re-checking it (scripts/verify_report.py)
    (out_dir / "meta.json").write_text(json.dumps({"set": set_name, "prs": sorted(prs) if prs else None, "repeats": repeats,
                                                    "models": [m.id for m in models], "tiers": tiers, "profile": profile, "beta": beta}, indent=1))
    table = []
    for row in rows:
        s = config_scores(row, profile, beta, lookup)
        s_all = config_scores(row, "all", beta, lookup)
        u = row["usage"]
        a = agreement(row) if row["voteds"] else {}
        table.append({
            "model": row["model"].id, "family": row["model"].family, "tier": row["tier"], "route": row["model"].route,
            "repeats": s["repeats"] if s else 0, "prs": s["prs"] if s else 0,
            "precision": s["precision"] if s else None, "recall": s["recall"] if s else None,
            "f1": s["f1"] if s else None, f"f{beta:g}": s["fbeta"] if s else None,
            "f1_sd": s["f1_sd"] if s else None, f"f{beta:g}_ci_low": (s["ci"] or (None, None))[0] if s else None, f"f{beta:g}_ci_high": (s["ci"] or (None, None))[1] if s else None,
            "tp": s["tp"] if s else None, "fp": s["fp"] if s else None, "fn": s["fn"] if s else None,
            "f1_all": s_all["f1"] if s_all else None, "recall_all": s_all["recall"] if s_all else None,
            "findings_per_pr": u["findings_per_pr"], "cost_per_pr": u["cost_list_per_pr"], "cost_uncached_per_pr": u["cost_uncached_per_pr"],
            "cost_reported_per_pr": u["cost_reported_per_pr"], "cost_total": u["cost_list_total"],
            "input_per_pr": u["tokens_per_pr"]["input"], "cache_read_per_pr": u["tokens_per_pr"]["cache_read"], "output_per_pr": u["tokens_per_pr"]["output"],
            "reasoning_per_pr": u["tokens_per_pr"]["reasoning"], "latency_median_s": u["latency_median_s"], "latency_p90_s": u["latency_p90_s"],
            "runs": u["runs"], "parse_errors": u["parse_errors"], "salvaged": u["salvaged"], "errors": u["errors"], "incomplete_votes": s["incomplete"] if s else None,
            "kappa_golden": a.get("kappa_golden"), "unanimous_golden": a.get("unanimous_golden"),
        })
    fb = f"f{beta:g}"
    sort_col = fb if sort_key != "f1" else "f1"
    table.sort(key=lambda r: (r[sort_col] is None, -(r[sort_col] or 0)))
    write_csv(out_dir / "configs.csv", table)

    lines = [f"# Code review benchmark: set `{set_name}`", "",
             (f"Profile `{profile}` ({', '.join(sorted(PROFILES[profile]))}); F{beta:g} alongside F1; repeats {repeats}; "
              f"three judges per model from outside its family, majority vote. Costs at list price per pull request."), ""]

    def md_table(rs: list[dict], title: str) -> None:
        lines.extend([f"## {title}", "", f"| model | tier | P | R | F1 | {fb.upper()} | {fb.upper()} 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |",
                      "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"])
        for r in rs:
            ci = f"{_pct(r[f'{fb}_ci_low'])}–{_pct(r[f'{fb}_ci_high'])}" if r[f"{fb}_ci_low"] is not None else ""
            lines.append(f"| {r['model']} | {r['tier']} | {_pct(r['precision'])} | {_pct(r['recall'])} | {_pct(r['f1'])} | {_pct(r[fb])} | {ci} | "
                         f"{_num(r['findings_per_pr'], 1)} | {_usd(r['cost_per_pr'])} | {_usd(r['cost_uncached_per_pr'])} | {_num(r['output_per_pr'])} | "
                         f"{_num(r['reasoning_per_pr'])} | {_num(r['latency_median_s'], 0)} | {_num(r['latency_p90_s'], 0)} | {_num(r['kappa_golden'], 2)} |")
        lines.append("")

    judged_rows = [r for r in table if r["prs"]]
    md_table(judged_rows, "Every configuration")
    md_table([r for r in judged_rows if r["tier"] == "default"], "Vendor default tier")
    best: dict[str, dict] = {}
    for r in judged_rows:
        if r["model"] not in best or (r[sort_col] or 0) > (best[r["model"]][sort_col] or 0):
            best[r["model"]] = r
    md_table(sorted(best.values(), key=lambda r: -(r[sort_col] or 0)), "Best tier per model")

    # slices: language, repository, PR labels; recall by golden category and severity; precision by the model's own category
    slice_rows, cat_rows, sev_rows, prec_rows, judge_rows = [], [], [], [], []
    for row in rows:
        if not row["voteds"]:
            continue
        name = f"{row['model'].id}/{row['tier']}"
        by_url: dict[str, dict] = {}
        for v in row["voteds"]:
            for url, r in v.items():
                by_url.setdefault(url, []).append(r)
        for dim_row in _slices_pooled(by_url, profile, beta, lookup, labels, index):
            slice_rows.append({"config": name, **dim_row})
        pooled_v = {f"{u}#{i}": r for u, rs in by_url.items() for i, r in enumerate(rs)}
        for x in recall_by(pooled_v, "category", lookup):
            cat_rows.append({"config": name, **x})
        for x in recall_by(pooled_v, "severity", lookup):
            sev_rows.append({"config": name, **x})
        by_rep = {f"{u}#{rep}": r for rep, v in zip(row["reps"], row["voteds"]) for u, r in v.items()}
        runs_by_rep = {f"{r['golden_url']}#{r['repeat']}": r for r in row["runs"]}
        for x in precision_by_category(by_rep, runs_by_rep):
            prec_rows.append({"config": name, **x})
        judge_rows.append({"config": name, **{f"f{beta:g}_{j}": v for j, v in per_judge_scores(row, profile, beta, lookup).items()},
                           **{f"agree_{j}": v for j, v in observer_agreement(row).items()}})
    write_csv(out_dir / "slices.csv", slice_rows)
    write_csv(out_dir / "recall_by_category.csv", cat_rows)
    write_csv(out_dir / "recall_by_severity.csv", sev_rows)
    write_csv(out_dir / "precision_by_model_category.csv", prec_rows)
    write_csv(out_dir / "per_judge.csv", judge_rows)

    best_names = {f"{r['model']}/{r['tier']}" for r in best.values()}
    for dim in ("language", "repo", "pr_size_category", "change_type", "review_difficulty", "requires_context"):
        sub = [r for r in slice_rows if r["dimension"] == dim and r["config"] in best_names]
        if not sub:
            continue
        values = sorted({r["value"] for r in sub})
        configs = [f"{r['model']}/{r['tier']}" for r in sorted(best.values(), key=lambda r: -(r[sort_col] or 0))]
        n_by_value = {r["value"]: r["prs"] for r in sub}
        lines.extend([f"## {fb.upper()} by {dim} (best tier per model; n = pull requests x repeats)", "",
                      "| config | " + " | ".join(f"{v} (n={n_by_value[v]})" for v in values) + " |", "|---|" + "---|" * len(values)])
        cell = {(r["config"], r["value"]): r for r in sub}
        for c in configs:
            vals = [cell.get((c, v)) for v in values]
            lines.append(f"| {c} | " + " | ".join("" if x is None else (_pct(x['fbeta']) + ("*" if x["prs"] < 10 else "")) for x in vals) + " |")
        lines.extend(["", "`*` fewer than 10 pull requests: read as a hint, not a result.", ""])
    for title, rs, key in (("Recall by golden category", cat_rows, "category"), ("Recall by golden severity", sev_rows, "severity")):
        sub = [r for r in rs if r["config"] in best_names]
        if not sub:
            continue
        values = sorted({r[key] for r in sub})
        n_by = {}
        for r in sub:
            n_by[r[key]] = max(n_by.get(r[key], 0), r["goldens"])
        lines.extend([f"## {title} (best tier per model)", "", "| config | " + " | ".join(f"{v} (n={n_by[v]})" for v in values) + " |", "|---|" + "---|" * len(values)])
        cell = {(r["config"], r[key]): r for r in sub}
        for c in [f"{r['model']}/{r['tier']}" for r in sorted(best.values(), key=lambda r: -(r[sort_col] or 0))]:
            lines.append(f"| {c} | " + " | ".join(_pct(cell[(c, v)]["recall"]) if (c, v) in cell else "" for v in values) + " |")
        lines.append("")
    if judge_rows:
        jids = sorted({k for r in judge_rows for k in r if k != "config" and not k.startswith("agree_")})
        aids = sorted({k for r in judge_rows for k in r if k.startswith("agree_")})
        lines.extend([f"## Each judge's own {fb.upper()} (judge sensitivity)"
                      + ("; observers' agreement with the panel's verdict per golden" if aids else ""), "",
                      "| config | " + " | ".join(j.split("_", 1)[1] for j in jids) + "".join(f" | agree {a[6:]}" for a in aids) + " |",
                      "|---|" + "---|" * (len(jids) + len(aids))])
        for r in judge_rows:
            lines.append(f"| {r['config']} | " + " | ".join(_pct(r.get(j)) for j in jids) + "".join(f" | {_pct(r.get(a))}" for a in aids) + " |")
        lines.append("")
    skipped = [(m.id, t, why) for m in models for t in tiers if (why := tier_skip(m, t))]
    if skipped:
        lines.extend(["## Not run", "", "| model | tier | why |", "|---|---|---|"])
        lines.extend(f"| {m} | {t} | {why} |" for m, t, why in skipped)
        lines.append("")
    path = out_dir / "report.md"
    path.write_text("\n".join(lines))
    return path


def _slices_pooled(by_url: dict[str, list[dict]], profile: str, beta: float, lookup: dict, labels: dict, index: dict) -> list[dict]:
    from .metrics import LABEL_DIMENSIONS
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for url in by_url:
        lab = labels.get(url, {})
        derived, llm = lab.get("derived") or {}, lab.get("llm_pr_labels") or {}
        entry = index.get(url, {})
        groups[("language", derived.get("language") or entry.get("language") or "?")].append(url)
        groups[("repo", (entry.get("source_repo") or "?").replace("-greptile", "").replace("-graphite", ""))].append(url)
        for dim in LABEL_DIMENSIONS:
            if llm.get(dim):
                groups[(dim, str(llm[dim]))].append(url)
    out = []
    for (dim, value), urls in sorted(groups.items()):
        pooled_v = {f"{u}#{i}": r for u in urls for i, r in enumerate(by_url[u])}
        s = score_counts(per_pr_counts(pooled_v, profile, lookup), beta)
        out.append({"dimension": dim, "value": value, **s})
    return out


def frontier_view(models: list[Model], tiers: list[str], repeats_full: list[int], repeats_frontier: list[int], pricing: dict,
                  profile: str = "core", beta: float = 2.0, name: str = "frontier") -> Path:
    """Every model on the frontier subset: the full-set models' rows restricted to the subset's pull requests, beside the
    frontier-only models."""
    lookup = golden_lookup()
    sub = {e["golden_url"] for e in load_set(ROOT / "data" / "sets" / "frontier.json")}
    rows = collect(models, tiers, "full", repeats_full, pricing) + collect(models, tiers, "frontier", repeats_frontier, pricing)
    table = []
    for row in rows:
        s = config_scores(row, profile, beta, lookup, sub)
        if not s:
            continue
        runs = [r for r in row["runs"] if r.get("golden_url") in sub]
        u = usage_summary(runs, pricing.get(row["model"].id))
        table.append({"model": row["model"].id, "tier": row["tier"], "set": "frontier" if "frontier" in row["model"].sets else "full",
                      "prs": s["prs"], "precision": s["precision"], "recall": s["recall"], "f1": s["f1"], f"f{beta:g}": s["fbeta"],
                      "cost_per_pr": u["cost_list_per_pr"], "latency_median_s": u["latency_median_s"]})
    table.sort(key=lambda r: -(r[f"f{beta:g}"] or 0))
    out_dir = REPORTS / name       # a named report gets its own view (frontier-view-<name>), so a later pass keeps an earlier one's
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "configs.csv", table)
    fb = f"f{beta:g}".upper()
    lines = ["# Frontier subset: every model on the same ten pull requests", "", f"| model | tier | from | n | P | R | F1 | {fb} | $/PR | median s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in table:
        lines.append(f"| {r['model']} | {r['tier']} | {r['set']} | {r['prs']} | {_pct(r['precision'])} | {_pct(r['recall'])} | {_pct(r['f1'])} | "
                     f"{_pct(r[f'f{beta:g}'])} | {_usd(r['cost_per_pr'])} | {_num(r['latency_median_s'])} |")
    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path
