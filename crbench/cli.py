"""crbench: build the data, probe the models, run the reviews, judge them, report.

  crbench data                     clone Martian's benchmark (pinned), build the PR index, fetch the PR snapshots, pick the frontier subset
  crbench estimate --set full      prompt sizes and the projected cost of one pass
  crbench probe [--judges]         one small call per (model, tier) [and per judge]
  crbench run --set full           the review calls (resumable)
  crbench cost --set full          tokens and cost of the runs so far, and of N more repeats
  crbench judge --set full         the benchmark's dedup and judge steps, three judges per model, voted
  crbench report --set full        reports/<set>/report.md and CSVs (and reports/frontier/)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import defaultdict

from .config import TIERS, configs_for, load_judges, load_models, load_pricing, load_runs, tool_name
from .env import ROOT, load_env
from .usage_log import read_rows


def _list(s: str | None) -> list[str] | None:
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def _repeats(s: str) -> list[int]:
    out: list[int] = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part.strip():
            out.append(int(part))
    return sorted(set(out))


def _models(args):
    models = load_models()
    only = set(_list(args.models) or [])
    unknown = only - {m.id for m in models}
    if unknown:
        raise SystemExit(f"unknown models: {sorted(unknown)}")
    return models, (only or None)


def _selected(args):
    """The models a command reports on: --models, or every model."""
    models, only = _models(args)
    return [m for m in models if not only or m.id in only]


def cmd_data(args) -> int:
    from .dataset import build_index, build_prs, fetch_martian, make_subset
    path = fetch_martian(force=args.force)
    print(f"benchmark at {path}")
    index = build_index()
    print(f"{len(index)} pull requests, {sum(e['golden_count'] for e in index)} golden comments")
    build_prs(index, force=args.force)
    sub = make_subset(index, per_repo=args.per_repo)
    print(f"frontier subset: {[e['id'] for e in sub]}")
    return 0


def cmd_estimate(args) -> int:
    from .dataset import load_pr, load_set
    from .prompt import build_prompt
    from .runner import runs_of
    cfg = load_runs()
    models, only = _models(args)
    pricing = load_pricing()
    entries = load_set(cfg.sets[args.set])
    system_text, user_t = cfg.prompt.system.read_text(), cfg.prompt.user.read_text()
    sizes = {}
    for e in entries:
        p = build_prompt(load_pr(e["id"]), cfg.prompt, system_text, user_t)
        sizes[e["id"]] = (p.chars, len(p.patch_only), len(p.cut_patches))
    chars = [s[0] for s in sizes.values()]
    tok = [c / args.chars_per_token for c in chars]
    print(f"{len(entries)} PRs: prompt chars median {statistics.median(chars):,.0f}, max {max(chars):,} "
          f"(~{statistics.median(tok):,.0f} / {max(tok):,.0f} tokens at {args.chars_per_token} chars/token); total ~{sum(tok):,.0f} input tokens per pass")
    assumed = {"low": args.out_low, "default": args.out_default, "xhigh": args.out_xhigh}
    total = 0.0
    print(f"\n{'config':<34} {'in $/pass':>10} {'out tok/PR':>11} {'src':>8} {'$/pass':>9}")
    for m, tier in configs_for(models, list(TIERS), args.set, only):
        price = pricing.get(m.id) or {}
        if price.get("input") is None:
            print(f"{m.id}/{tier:<20} no price")
            continue
        measured = [r["usage"]["output"] for r in runs_of(m.id, tier) if r and r.get("status") in ("ok", "parse_error")]
        out_tok = statistics.mean(measured) if measured else assumed[tier]
        src = f"n={len(measured)}" if measured else "assumed"
        cin = sum(tok) * price["input"] / 1e6
        cout = out_tok * len(entries) * price["output"] / 1e6
        total += cin + cout
        print(f"{m.id + '/' + tier:<34} {cin:>10.2f} {out_tok:>11,.0f} {src:>8} {cin + cout:>9.2f}")
    print(f"\nprojected review cost of one pass: ${total:,.2f} (list prices; judging not included)")
    return 0


def _probe_line(r: dict) -> str:
    u = r.get("usage") or {}
    err = (r.get("error") or "")[:220]
    if r["kind"] == "model":
        extra = (f"in {u.get('input')} out {u.get('output')} reasoning {u.get('reasoning')} cache {u.get('cache_read')} cost {r.get('cost_reported')} "
                 f"served {r.get('served_model')} {r.get('provider_served') or ''} finish {r.get('finish_reason')}") if u else ""
        return f"{r['id'] + '/' + r['tier']:<34} {r['status']:<11} {r.get('seconds', '')!s:>6}s findings {r.get('findings', '')} {extra} {err}"
    return f"judge {r['id']:<26} {r['status']:<11} {r.get('seconds', '')}s verdict {r.get('verdict')} usage {u} {err}"


def cmd_probe(args) -> int:
    from .probe import probe_judges, probe_models, save
    cfg = load_runs()
    models, only = _models(args)
    tiers = _list(args.tiers) or list(TIERS)
    rows = []

    def show(r):
        print(_probe_line(r), flush=True)

    if not args.judges_only:
        sel = [m for m in models if not only or m.id in only]
        rows += asyncio.run(probe_models(sel, tiers, cfg, args.max_output_tokens, timeout=args.timeout, on_row=show))
    if args.judges or args.judges_only:
        rows += probe_judges(load_judges(), on_row=show)
    print(f"-> {save(rows)}")
    return 0 if all(r["status"] in ("ok", "alias") for r in rows) else 1


def cmd_run(args) -> int:
    from .runner import run_matrix
    cfg = load_runs()
    models, only = _models(args)
    tiers = _list(args.tiers) or list(TIERS)
    reps = _repeats(args.repeats)
    res = asyncio.run(run_matrix(models, tiers, args.set, cfg, reps, only=only, limit=args.limit, force=args.force, dry_run=args.dry_run,
                                 prs=set(_list(args.prs) or []) or None))
    print(json.dumps(res))
    return 0 if not res.get("errors") else 1


def _set_urls(cfg, set_name: str, prs: str | None) -> set[str]:
    from .dataset import load_set
    wanted = set(_list(prs) or [])
    return {e["golden_url"] for e in load_set(cfg.sets[set_name]) if not wanted or e["id"] in wanted}


def _usage_rows(models, only, tiers, set_name, reps, prs=None):
    from .metrics import usage_summary
    from .runner import runs_of
    cfg = load_runs()
    pricing = load_pricing()
    urls = _set_urls(cfg, set_name, prs)
    out = []
    for m, tier in configs_for(models, tiers, set_name, only):
        runs = [r for r in runs_of(m.id, tier) if r and r.get("golden_url") in urls and r.get("repeat") in reps]
        out.append((m, tier, usage_summary(runs, pricing.get(m.id))))
    return out


def cmd_cost(args) -> int:
    from .metrics import cost_list
    models, only = _models(args)
    tiers = _list(args.tiers) or list(TIERS)
    reps = _repeats(args.repeats)
    rows = _usage_rows(models, only, tiers, args.set, reps, args.prs)
    print(f"{'config':<34} {'runs':>5} {'err':>4} {'in/PR':>9} {'cache/PR':>9} {'out/PR':>8} {'reas/PR':>8} {'$/PR':>8} {'$ uncached/PR':>13} {'$ reported':>10} {'$ total':>9} {'med s':>6} {'p90 s':>6}")
    total = 0.0
    for m, tier, u in rows:
        t = u["tokens_per_pr"]
        f = lambda x, d=0: "" if x is None else f"{x:,.{d}f}"
        total += u["cost_list_total"] or 0
        print(f"{m.id + '/' + tier:<34} {u['runs']:>5} {u['errors'] + u['parse_errors']:>4} {f(t['input']):>9} {f(t['cache_read']):>9} {f(t['output']):>8} {f(t['reasoning']):>8} "
              f"{f(u['cost_list_per_pr'], 4):>8} {f(u['cost_uncached_per_pr'], 4):>13} {f(u['cost_reported_total'], 2):>10} {f(u['cost_list_total'], 2):>9} "
              f"{f(u['latency_median_s']):>6} {f(u['latency_p90_s']):>6}")
    print(f"\nreview cost so far (list prices): ${total:,.2f}")
    if args.more_repeats:
        print(f"{args.more_repeats} more repeats of the same configs: ~${total * args.more_repeats:,.2f}")
    # judges
    jdir = ROOT / "results" / "judge_usage"
    if jdir.exists():
        pricing = load_pricing()
        print(f"\n{'judge':<20} {'calls':>7} {'errors':>7} {'in':>12} {'out':>11} {'$ list':>9} {'$ reported':>10}")
        jtotal = 0.0
        for p in sorted(jdir.glob("*.jsonl")):
            calls = read_rows(p)[0]
            agg = defaultdict(int)
            reported, usd = 0.0, 0.0
            for c in calls:
                for k, v in (c.get("usage") or {}).items():
                    agg[k] += v or 0
                reported += c.get("cost_reported") or 0
                usd += cost_list(c.get("usage") or {}, pricing.get(p.stem)) or 0
            jtotal += usd or 0
            print(f"{p.stem:<20} {len(calls):>7} {sum(1 for c in calls if c['status'] != 200):>7} {agg['input'] + agg['cache_read']:>12,} {agg['output']:>11,} "
                  f"{(usd or 0):>9.2f} {reported:>10.2f}")
        print(f"judging cost so far (list prices): ${jtotal:,.2f}")
    return 0


def cmd_judge(args) -> int:
    from .judge import judge_calls_estimate, judge_tools, plan
    from .metrics import golden_lookup
    from .runner import runs_of
    cfg = load_runs()
    models, only = _models(args)
    tiers = _list(args.tiers) or list(TIERS)
    reps = _repeats(args.repeats)
    pool = load_judges()
    urls = _set_urls(cfg, args.set, args.prs)
    lookup = golden_lookup()
    gcount = defaultdict(int)
    for g in lookup.values():
        gcount[g["url"]] += 1
    tools, runs_by_tool = [], {}
    for m, tier in configs_for(models, tiers, args.set, only):
        all_runs = runs_of(m.id, tier)
        for rep in reps:
            runs = [r for r in all_runs if r and r.get("repeat") == rep and r.get("golden_url") in urls]
            if not runs:
                continue
            missing = len(urls) - len(runs)
            errors = sum(1 for r in runs if r.get("status") == "error")
            if (missing or errors) and not args.allow_partial:
                print(f"{m.id}/{tier}/r{rep}: {missing} PRs not run, {errors} errored; skipped (--allow-partial to judge anyway)")
                continue
            t = tool_name(m.id, tier, rep)
            tools.append(t)
            runs_by_tool[t] = runs
    if not tools:
        print("nothing to judge")
        return 1
    triples, _, observers = plan(tools, {m.id: m for m in models}, pool)
    calls = defaultdict(int)
    for t in tools:
        n = judge_calls_estimate(runs_by_tool[t], gcount)
        for j in triples[t] + observers[t]:
            calls[j.id] += n
    print(f"{len(tools)} tools; match calls per judge: " + ", ".join(f"{j} {n:,}" for j, n in sorted(calls.items())))
    if args.dry_run:
        return 0
    judge_tools(tools, runs_by_tool, {m.id: m for m in models}, pool, shards=args.shards, force=args.force)
    return 0


def cmd_check(args) -> int:
    from .check import check
    models = _selected(args)
    tiers = _list(args.tiers) or list(TIERS)
    rows = check(models, tiers, args.set, load_runs(), load_judges(), _repeats(args.repeats), set(_list(args.prs) or []) or None)
    bad = 0
    for r in rows:
        mark = "OK " if not r["problems"] else "BAD"
        bad += bool(r["problems"])
        print(f"{mark} {r['config']:<34} {r['route']:<18} served {','.join(r['served']):<26} findings {r['findings']:>3}  judges {'+'.join(r['judges'])}"
              + (f" | observer {'+'.join(r['observers'])}" if r["observers"] else ""))
        for p in r["problems"]:
            print(f"      - {p}")
        for n in r.get("notes") or []:
            print(f"      . {n}")
    print(f"{len(rows) - bad}/{len(rows)} configurations ready")
    return 0 if not bad else 1


def cmd_export(args) -> int:
    from .export import _main
    _main()
    return 0


def cmd_report(args) -> int:
    from .report import build, frontier_view
    models = _selected(args)
    tiers = _list(args.tiers) or list(TIERS)
    pricing = load_pricing()
    path = build(models, tiers, args.set, _repeats(args.repeats), pricing, profile=args.profile, beta=args.beta, sort_key=args.sort,
                 prs=set(_list(args.prs) or []) or None, name=args.name)
    print(f"-> {path}")
    if args.frontier:
        print(f"-> {frontier_view(models, tiers, _repeats(args.repeats), _repeats(args.frontier_repeats or args.repeats), pricing, profile=args.profile, beta=args.beta, name=f'frontier-view-{args.name}' if args.name else 'frontier')}")
    return 0


def main(argv=None) -> int:
    load_env()
    ap = argparse.ArgumentParser(prog="crbench", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, set_default="full"):
        p.add_argument("--set", default=set_default, choices=["full", "frontier"])
        p.add_argument("--models", help="comma-separated model ids (default: every model of the set)")
        p.add_argument("--tiers", help=f"comma-separated tiers (default: {','.join(TIERS)})")
        p.add_argument("--repeats", default="1", help="repeat numbers: 1 | 1-3 | 2,3")
        p.add_argument("--prs", help="comma-separated pull request ids (default: the whole set)")

    p = sub.add_parser("data")
    p.add_argument("--force", action="store_true")
    p.add_argument("--per-repo", type=int, default=2)
    p.set_defaults(fn=cmd_data)

    p = sub.add_parser("estimate")
    common(p)
    p.add_argument("--chars-per-token", type=float, default=3.6)
    p.add_argument("--out-low", type=int, default=3000)
    p.add_argument("--out-default", type=int, default=8000)
    p.add_argument("--out-xhigh", type=int, default=20000)
    p.set_defaults(fn=cmd_estimate)

    p = sub.add_parser("probe")
    p.add_argument("--models")
    p.add_argument("--tiers")
    p.add_argument("--judges", action="store_true", help="probe the judge pool too")
    p.add_argument("--judges-only", action="store_true")
    p.add_argument("--max-output-tokens", type=int, default=16000)
    p.add_argument("--timeout", type=float, default=240, help="seconds per call (two attempts)")
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("run")
    common(p)
    p.add_argument("--limit", type=int, help="only the first N pull requests of the set")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("cost")
    common(p)
    p.add_argument("--more-repeats", type=int, default=0)
    p.set_defaults(fn=cmd_cost)

    p = sub.add_parser("judge")
    common(p)
    p.add_argument("--shards", type=int, default=8, help="lanes per judge (tools judged at once by one judge); a tool stays in the lane that took it first")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-partial", action="store_true")
    p.set_defaults(fn=cmd_judge)

    p = sub.add_parser("check")
    common(p)
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("export", help="every run, call, finding, verdict and judge call as CSV tables in results/dataset/")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("report")
    common(p)
    p.add_argument("--profile", default="core", choices=["strict", "core", "all"])
    p.add_argument("--beta", type=float, default=2.0)
    p.add_argument("--sort", default="f1", choices=["f1", "fbeta"])
    p.add_argument("--frontier", action="store_true", help="also write the frontier view")
    p.add_argument("--frontier-repeats", default=None, help="repeats of the frontier-only models (default: the same as --repeats)")
    p.add_argument("--name", help="report directory under reports/ (default: the set, plus the pull requests if --prs)")
    p.set_defaults(fn=cmd_report)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        print("\ninterrupted: what finished is saved; the same command resumes from there", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
