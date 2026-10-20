"""Scores from voted rows: the benchmark's profiles (strict, core, all) with matched-excluded handling, F-beta,
bootstrap intervals over pull requests, slices by the benchmark's PR labels and by golden category and severity,
and the usage and cost of the runs behind them."""
from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict

from .dataset import MARTIAN_COPY

PROFILES: dict[str, frozenset[str]] = {
    "strict": frozenset({"bug", "security", "concurrency", "data", "api"}),
    "core": frozenset({"bug", "security", "concurrency", "data", "api", "perf", "test_gap", "doc_defect"}),
    "all": frozenset({"bug", "security", "concurrency", "data", "api", "perf", "test_gap", "doc_defect", "style", "speculative"}),
}
LABEL_DIMENSIONS = ("pr_size_category", "domain", "change_type", "code_complexity", "review_difficulty", "risk_level", "requires_context", "primary_concern")


def fbeta(p: float, r: float, beta: float) -> float:
    b2 = beta * beta
    return (1 + b2) * p * r / (b2 * p + r) if (b2 * p + r) > 0 else 0.0


def golden_lookup() -> dict[str, dict]:
    """{golden comment text: {category, severity, url}} from the copied golden files."""
    out: dict[str, dict] = {}
    for path in sorted((MARTIAN_COPY / "golden_comments").glob("*.json")):
        with open(path) as f:
            for entry in json.load(f):
                for gc in entry.get("comments", []):
                    out[gc["comment"]] = {"category": gc.get("category"), "severity": gc.get("severity"), "url": entry.get("url")}
    return out


def pr_labels() -> dict[str, dict]:
    with open(MARTIAN_COPY / "pr_labels.json") as f:
        return json.load(f)


def _category(x: dict, lookup: dict) -> str:
    return x.get("category") or lookup.get(x.get("golden_comment", ""), {}).get("category") or ""


def per_pr_counts(voted: dict, profile: str, lookup: dict, urls: set[str] | None = None) -> dict[str, tuple[int, int, int]]:
    cats = PROFILES[profile]
    out = {}
    for url, row in voted.items():
        if row.get("incomplete") or (urls is not None and url not in urls):
            continue
        tp = sum(1 for x in row["true_positives"] if _category(x, lookup) in cats)
        fn = sum(1 for x in row["false_negatives"] if _category(x, lookup) in cats)
        out[url] = (tp, row["fp"], fn)
    return out


def score_counts(counts: dict[str, tuple[int, int, int]], beta: float) -> dict:
    tp = sum(c[0] for c in counts.values())
    fp = sum(c[1] for c in counts.values())
    fn = sum(c[2] for c in counts.values())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"prs": len(counts), "tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": fbeta(p, r, 1.0), "fbeta": fbeta(p, r, beta)}


def bootstrap_ci(counts: dict[str, tuple[int, int, int]], beta: float, n: int = 2000, seed: int = 1) -> tuple[float, float] | None:
    rows = list(counts.values())
    if len(rows) < 2:
        return None
    rnd = random.Random(seed)
    samples = []
    for _ in range(n):
        pick = [rows[rnd.randrange(len(rows))] for _ in rows]
        tp, fp, fn = (sum(c[i] for c in pick) for i in range(3))
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        samples.append(fbeta(p, r, beta))
    samples.sort()
    return samples[int(0.025 * n)], samples[min(n - 1, int(0.975 * n))]


def score(voted: dict, profile: str, beta: float, lookup: dict, urls: set[str] | None = None, ci: bool = True) -> dict:
    counts = per_pr_counts(voted, profile, lookup, urls)
    s = score_counts(counts, beta)
    s["ci"] = bootstrap_ci(counts, beta) if ci else None
    return s


def recall_by(voted: dict, key: str, lookup: dict) -> list[dict]:
    """Recall of the golden comments grouped by `category` or `severity` (every profile's goldens)."""
    tp: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    for row in voted.values():
        if row.get("incomplete"):
            continue
        for x in row["true_positives"]:
            k = x.get(key) or lookup.get(x.get("golden_comment", ""), {}).get(key) or "?"
            tp[k] += 1
            total[k] += 1
        for x in row["false_negatives"]:
            k = x.get(key) or lookup.get(x.get("golden_comment", ""), {}).get(key) or "?"
            total[k] += 1
    return [{key: k, "tp": tp[k], "goldens": total[k], "recall": tp[k] / total[k] if total[k] else 0.0} for k in sorted(total)]


def precision_by_category(voted: dict, runs: dict) -> list[dict]:
    """Precision of the candidates grouped by the category the model itself gave them: every finding of a judged
    review counts, a finding the panel voted a false positive is one (as in the scores), any other is not.
    `voted` and `runs` share keys ("<url>#<repeat>")."""
    from .prompt import finding_text
    fp: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    for key, row in voted.items():
        run = runs.get(key)
        if row.get("incomplete") or run is None:
            continue
        fps = {x["candidate"] for x in row["false_positives"]}
        cats = {finding_text(f): f.get("category") or "?" for f in run.get("findings", []) if finding_text(f).strip()}
        for text, k in cats.items():
            total[k] += 1
            fp[k] += text in fps
    return [{"category": k, "candidates": total[k], "fp": fp[k], "precision": (total[k] - fp[k]) / total[k] if total[k] else 0.0} for k in sorted(total)]


def prompt_tokens(usage: dict) -> int:
    return usage.get("input", 0) + usage.get("cache_read", 0) + usage.get("cache_write", 0)


def price_for(usage: dict, price: dict | None) -> dict | None:
    """The rates one request pays: a model's `long_context` rates replace its base rates for every token of a request
    whose prompt (input, cache reads and cache writes together) is over `long_context.over` tokens."""
    if not price:
        return price
    lc = price.get("long_context")
    if lc and prompt_tokens(usage) > lc["over"]:
        return {**price, **{k: v for k, v in lc.items() if k != "over"}}
    return price


def cost_list(usage: dict, price: dict | None) -> float | None:
    """List-price dollars of one request's usage."""
    price = price_for(usage, price)
    if not price or price.get("input") is None or price.get("output") is None:
        return None
    total = usage.get("input", 0) * price["input"] + usage.get("output", 0) * price["output"]
    total += usage.get("cache_read", 0) * (price.get("cache_read") or price["input"])
    total += usage.get("cache_write", 0) * (price.get("cache_write") or price["input"])
    return total / 1_000_000


def cost_uncached(usage: dict, price: dict | None) -> float | None:
    """The cost had nothing been read from or written to a cache: every input token at the input price. Repeats of one
    prompt hit implicit caches on some routes and not others; this is the like-for-like figure across models."""
    price = price_for(usage, price)
    if not price or price.get("input") is None or price.get("output") is None:
        return None
    return (prompt_tokens(usage) * price["input"] + usage.get("output", 0) * price["output"]) / 1_000_000


def run_cost(run: dict, price: dict | None, fn=cost_list) -> float | None:
    """A run's cost, request by request (a parse retry is a second request, and long-context rates are per request)."""
    calls = [c.get("usage") or {} for c in run.get("calls") or []] or [run.get("usage") or {}]
    costs = [fn(u, price) for u in calls]
    return None if any(c is None for c in costs) else sum(costs)


def usage_summary(runs: list[dict], price: dict | None) -> dict:
    ok = [r for r in runs if r.get("status") in ("ok", "parse_error")]
    tokens = {k: sum((r.get("usage") or {}).get(k) or 0 for r in ok) for k in ("input", "output", "cache_read", "cache_write")}
    reasoning = [x for r in ok if (x := (r.get("usage") or {}).get("reasoning")) is not None]  # not every route reports it
    tokens["reasoning"] = sum(reasoning) if reasoning else None
    costs = [run_cost(r, price) for r in ok]
    uncached = [run_cost(r, price, cost_uncached) for r in ok]
    reported = [r.get("cost_reported") for r in ok if r.get("cost_reported") is not None]
    latencies = sorted(r.get("latency_ms", 0) / 1000 for r in ok)
    return {
        "runs": len(runs), "ok": sum(1 for r in runs if r.get("status") == "ok"), "parse_errors": sum(1 for r in runs if r.get("status") == "parse_error"),
        "errors": sum(1 for r in runs if r.get("status") == "error"), "salvaged": sum(1 for r in runs if r.get("salvaged")), "tokens": tokens,
        "cost_list_total": sum(c for c in costs if c is not None) if any(c is not None for c in costs) else None,
        "cost_list_per_pr": (sum(c for c in costs if c is not None) / len(ok)) if ok and all(c is not None for c in costs) else None,
        "cost_uncached_per_pr": (sum(c for c in uncached if c is not None) / len(ok)) if ok and all(c is not None for c in uncached) else None,
        "cost_reported_total": sum(reported) if reported else None,
        "cost_reported_per_pr": (sum(reported) / len(reported)) if reported else None,
        "latency_median_s": statistics.median(latencies) if latencies else None,
        "latency_p90_s": (statistics.quantiles(latencies, n=10, method="inclusive")[-1] if len(latencies) > 1 else latencies[0]) if latencies else None,
        "findings_per_pr": (sum(r.get("finding_count", 0) for r in ok) / len(ok)) if ok else None,
        "tokens_per_pr": {k: (v / (len(reasoning) if k == "reasoning" else len(ok)) if v is not None and ok else None) for k, v in tokens.items()},
        "http_attempts": sum(r.get("attempts", 0) for r in ok),
    }
