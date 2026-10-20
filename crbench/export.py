"""Everything the benchmark recorded, as analysis-ready tables (results/dataset/*.csv), one per entity and joined by
their ids, so any comparison can be made afterwards with a group-by: model, effort, route, pull request size,
language, repository, application stack (the benchmark's `domain` label), change type, complexity, difficulty, risk,
golden severity and category, the model's own severity and category, judge, cost, tokens, time.

  models.csv         a row per model: family, route, pin, sets, tier parameters, prices
  prs.csv            a row per pull request: repository, language, size, the benchmark's labels, golden mix, prompt
  goldens.csv        a row per golden comment: severity, category, profiles
  runs.csv           a row per (model, tier, pull request, repeat): status, tokens, cost, time, findings
  calls.csv          a row per API call of a run (a parse retry is a second call): timing, usage, ids, failed attempts
  findings.csv       a row per finding: the model's file, line, severity, category, text; the panel's verdict
                     (matches_golden, false_positive, unresolved: neither by majority, or not_judged)
  golden_results.csv a row per (run, golden comment): found by the panel or not, judges' yes votes, matching finding
  verdicts.csv       a row per (run, judge, golden or finding): that judge's own verdict, confidence and reasoning
  judge_calls.csv.gz a row per judge API call: judge, step, tool, tokens, cost, latency, status (gzipped: 600k rows)
"""
from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

from .config import load_judges, load_models, load_pricing, parse_tool_name, tier_params, tool_name
from .dataset import MARTIAN_COPY, load_pr, load_set
from .env import ROOT
from .judge import JUDGED
from .metrics import PROFILES, cost_list, cost_uncached, prompt_tokens, run_cost
from .prompt import finding_text
from .runner import RUNS, load_run
from .usage_log import read_rows

OUT = ROOT / "results" / "dataset"


def _write(name: str, rows: list[dict]) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for r in rows:
        fields.extend(k for k in r if k not in fields)
    opener = gzip.open if name.endswith(".gz") else open
    with opener(OUT / name, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
    return len(rows)


def _goldens() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for path in sorted((MARTIAN_COPY / "golden_comments").glob("*.json")):
        with open(path) as f:
            for entry in json.load(f):
                out[entry["url"]] = entry["comments"]
    return out


def export() -> dict[str, int]:
    models = load_models()
    pricing = load_pricing()
    with open(MARTIAN_COPY / "pr_labels.json") as f:
        labels = json.load(f)
    goldens = _goldens()
    sets = {name: {e["id"] for e in load_set(ROOT / "data" / "sets" / f"{name}.json")} for name in ("full", "frontier")}
    entries = load_set(ROOT / "data" / "sets" / "full.json")
    pr_of_url = {e["golden_url"]: e["id"] for e in entries}
    counts: dict[str, int] = {}

    # models
    rows = []
    for m in models:
        price = pricing.get(m.id) or {}
        rows.append({"model": m.id, "family": m.family, "route": m.route, "provider_model": m.model,
                     "provider_pin": (m.provider or {}).get("order"), "sets": m.sets,
                     **{f"tier_{t}": (spec.get("skip") and f"not run: {spec['skip']}") or tier_params(m, t)[0] for t, spec in m.tiers.items()},
                     **{f"price_{k}": v for k, v in price.items() if k != "long_context"},
                     "price_long_context": price.get("long_context")})
    counts["models.csv"] = _write("models.csv", rows)

    # pull requests and goldens
    prs, gold_rows = [], []
    golden_id: dict[tuple[str, str], str] = {}
    for e in entries:
        pr = load_pr(e["id"])
        lab = labels.get(e["golden_url"]) or {}
        llm, derived = lab.get("llm_pr_labels") or {}, lab.get("derived") or {}
        gs = goldens.get(e["golden_url"], [])
        files = pr.get("files") or []
        prs.append({"pr": e["id"], "golden_url": e["golden_url"], "in_full": e["id"] in sets["full"], "in_frontier": e["id"] in sets["frontier"],
                    "repository": (e.get("source_repo") or "").replace("-greptile", "").replace("-graphite", ""), "source_repo": e.get("source_repo"),
                    "language": e.get("language") or derived.get("language"), "title": pr.get("title"),
                    "changed_files": pr.get("changed_files", len(files)), "additions": pr.get("additions"), "deletions": pr.get("deletions"),
                    "size": llm.get("pr_size_category") or e.get("pr_size_category"), "domain": llm.get("domain"),
                    "change_type": llm.get("change_type"), "complexity": llm.get("code_complexity"), "difficulty": llm.get("review_difficulty"),
                    "risk": llm.get("risk_level"), "context": llm.get("requires_context"), "concern": llm.get("primary_concern"),
                    "bug_categories": llm.get("bug_categories"), "goldens": len(gs),
                    **{f"goldens_{s.lower()}": sum(1 for g in gs if (g.get("severity") or "").lower() == s.lower()) for s in ("Critical", "High", "Medium", "Low")},
                    **{f"goldens_{p}": sum(1 for g in gs if g.get("category") in cats) for p, cats in PROFILES.items()},
                    "benchmark_note": e.get("benchmark_note")})
        for i, g in enumerate(gs):
            gid = f"{e['id']}#g{i}"
            golden_id[(e["golden_url"], g["comment"])] = gid
            gold_rows.append({"golden": gid, "pr": e["id"], "severity": g.get("severity"), "category": g.get("category"),
                              **{f"in_{p}": g.get("category") in cats for p, cats in PROFILES.items()}, "text": g["comment"]})
    counts["prs.csv"] = _write("prs.csv", prs)
    counts["goldens.csv"] = _write("goldens.csv", gold_rows)

    # runs, calls, findings (and the run -> findings map the verdicts need)
    run_rows, call_rows, finding_rows = [], [], []
    finding_ids: dict[str, dict[str, str]] = {}      # run id -> candidate text -> finding id
    candidate_ids: dict[str, list[str]] = {}         # run id -> finding ids in the judge's candidate order
    for path in sorted(RUNS.glob("*/*/*.json")):
        r = load_run(path)
        if not r or not r.get("pr_id"):
            continue
        rid = tool_name(r["model_id"], r["tier"], r["repeat"]) + f"@{r['pr_id']}"
        price = pricing.get(r["model_id"])
        u = r.get("usage") or {}
        calls = r.get("calls") or []
        last = calls[-1] if calls else {}
        run_rows.append({"run": rid, "model": r["model_id"], "tier": r["tier"], "pr": r["pr_id"], "repeat": r["repeat"], "set": r.get("set"),
                         "route": r.get("route"), "provider_served": r.get("provider_served"), "served_model": r.get("served_model"),
                         "status": r.get("status"), "error": r.get("error"), "finish_reason": r.get("finish_reason"),
                         "calls": len(calls), "http_attempts": r.get("attempts"),
                         "failed_attempts": len(r.get("failed_attempts") or []) + sum(len(c.get("failed_attempts") or []) for c in calls),
                         "prompt_tokens": max((prompt_tokens(c.get("usage") or {}) for c in calls), default=None),
                         "input": u.get("input"), "cache_read": u.get("cache_read"), "cache_write": u.get("cache_write"),
                         "output": u.get("output"), "reasoning": u.get("reasoning"),
                         "cost_list": run_cost(r, price) if calls else None, "cost_uncached": run_cost(r, price, cost_uncached) if calls else None,
                         "cost_reported": r.get("cost_reported"), "latency_s": (r.get("latency_ms") or 0) / 1000 or None,
                         "first_text_s": last.get("first_text_ms") / 1000 if last.get("first_text_ms") is not None else None,
                         "findings": r.get("finding_count"), "salvaged": bool(r.get("salvaged")), "started_at": r.get("started_at"),
                         "prompt_chars": (r.get("prompt") or {}).get("chars"), "prompt_sha": (r.get("prompt") or {}).get("sha"),
                         "files_patch_only": len((r.get("prompt") or {}).get("patch_only") or []), "params": r.get("params"), "provider_pin": r.get("provider_pin")})
        for i, c in enumerate(calls):
            cu = c.get("usage") or {}
            call_rows.append({"run": rid, "call": i, "started_at": c.get("started_at"), "latency_s": (c.get("latency_ms") or 0) / 1000,
                              "first_chunk_s": c["first_chunk_ms"] / 1000 if c.get("first_chunk_ms") is not None else None,
                              "first_text_s": c["first_text_ms"] / 1000 if c.get("first_text_ms") is not None else None,
                              "finish_reason": c.get("finish_reason"), "prompt_tokens": prompt_tokens(cu), **cu,
                              "cost_list": cost_list(cu, price), "cost_reported": c.get("cost_reported"), "response_id": c.get("response_id"),
                              "provider_served": c.get("provider_served"), "http_attempts": c.get("http_attempts"),
                              "failed_attempts": c.get("failed_attempts"), "text_chars": c.get("text_chars")})
        finding_ids[rid], candidate_ids[rid] = {}, []
        for i, f in enumerate(r.get("findings") or []):
            fid = f"{rid}#f{i}"
            text = finding_text(f)
            if text.strip():
                finding_ids[rid].setdefault(text, fid)
                candidate_ids[rid].append(fid)
            finding_rows.append({"finding": fid, "run": rid, "model": r["model_id"], "tier": r["tier"], "pr": r["pr_id"], "repeat": r["repeat"],
                                 "file": f.get("file"), "line": f.get("line"), "model_severity": f.get("severity"), "model_category": f.get("category"),
                                 "title": f.get("title"), "body": f.get("body"), "chars": len(text)})
    counts["runs.csv"] = _write("runs.csv", run_rows)
    counts["calls.csv"] = _write("calls.csv", call_rows)

    # the panel's and each judge's verdicts
    verdict_of: dict[str, dict] = {}
    judged_runs: set[str] = set()
    gr_rows, v_rows = [], []
    for path in sorted(JUDGED.glob("*.json")):
        with open(path) as fh:
            rec = json.load(fh)
        model, tier, rep = parse_tool_name(rec["tool"])
        panel = [j["id"] for j in rec["judges"]]
        for url, v in rec["voted"].items():
            pr = pr_of_url.get(url)
            rid = f"{rec['tool']}@{pr}"
            fids = finding_ids.get(rid, {})
            if v.get("incomplete"):
                continue
            judged_runs.add(rid)
            for kind, items in (("found", v["true_positives"]), ("missed", v["false_negatives"])):
                for x in items:
                    gr_rows.append({"run": rid, "model": model, "tier": tier, "pr": pr, "repeat": rep, "golden": golden_id.get((url, x["golden_comment"])),
                                    "found": kind == "found", "judges_yes": len(x.get("judges_yes") or []), "yes_by": x.get("judges_yes"), "panel": panel,
                                    "matched_finding": fids.get(x.get("matched_candidate") or ""), "confidence": x.get("confidence")})
                    if kind == "found" and fids.get(x.get("matched_candidate") or ""):
                        verdict_of.setdefault(fids[x["matched_candidate"]], {"panel": "matches_golden", "golden": golden_id.get((url, x["golden_comment"]))})
            for x in v["false_positives"]:
                if fids.get(x["candidate"]):
                    verdict_of[fids[x["candidate"]]] = {"panel": "false_positive", "judges_fp": x.get("judges_fp")}
            groups = (rec.get("dedup_groups") or {}).get(url) or []
            cids = candidate_ids.get(rid, [])
            for gi, group in enumerate(groups):
                for ci in group:
                    if ci < len(cids):
                        verdict_of.setdefault(cids[ci], {})["dedup_group"] = gi
        for jid, rows in rec["per_judge"].items():
            for url, row in rows.items():
                pr = pr_of_url.get(url)
                rid = f"{rec['tool']}@{pr}"
                fids = finding_ids.get(rid, {})
                for kind, items in (("golden_found", row.get("true_positives", [])), ("golden_missed", row.get("false_negatives", []))):
                    for x in items:
                        v_rows.append({"run": rid, "judge": jid, "kind": kind, "golden": golden_id.get((url, x.get("golden_comment"))),
                                       "finding": fids.get(x.get("matched_candidate") or ""), "confidence": x.get("confidence"), "reasoning": x.get("reasoning")})
                for x in row.get("false_positives", []):
                    v_rows.append({"run": rid, "judge": jid, "kind": "finding_false_positive", "golden": None, "finding": fids.get(x.get("candidate", "")),
                                   "confidence": None, "reasoning": None})
    counts["golden_results.csv"] = _write("golden_results.csv", gr_rows)
    counts["verdicts.csv"] = _write("verdicts.csv", v_rows)
    for row in finding_rows:
        v = verdict_of.get(row["finding"], {})
        row.update({"panel": v.get("panel") or ("unresolved" if row["run"] in judged_runs else "not_judged"),
                    "matched_golden": v.get("golden"), "judges_fp": v.get("judges_fp"), "dedup_group": v.get("dedup_group")})
    counts["findings.csv"] = _write("findings.csv", finding_rows)

    # judge calls
    judges = {j.id: j for j in load_judges().pool}
    jc_rows = []
    for path in sorted((ROOT / "results" / "judge_usage").glob("*.jsonl")):
        jid = path.stem
        rows, junk = read_rows(path)
        if junk:
            print(f"{path.name}: {junk} lines that are not JSON, skipped")
        for c in rows:
            u = c.get("usage") or {}
            jc_rows.append({"ts": c.get("ts"), "judge": jid, "in_pool": jid in judges, "step": c.get("step"), "tool": c.get("tool"),
                            "status": c.get("status"), "latency_s": (c.get("latency_ms") or 0) / 1000, **u,
                            "cost_list": cost_list(u, pricing.get(jid)) if u else None, "cost_reported": c.get("cost_reported"), "error": c.get("error")})
    counts["judge_calls.csv.gz"] = _write("judge_calls.csv.gz", jc_rows)
    return counts


def _main() -> None:
    for name, n in export().items():
        print(f"{n:>8,}  {Path(OUT / name).relative_to(ROOT)}")
