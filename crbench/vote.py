"""The vote: a golden comment is a true positive when at least two of the three judges matched it; a candidate is a
false positive when at least two left it unmatched. Everything else follows the benchmark's own arithmetic
(precision = TP / candidates, recall = TP / goldens). Agreement is reported beside the counts."""
from __future__ import annotations


def _tp_texts(row: dict) -> set[str]:
    return {x.get("golden_comment", "") for x in row.get("true_positives", [])}


def _fp_texts(row: dict) -> set[str]:
    out = set()
    for x in row.get("false_positives", []):
        out.add(x.get("candidate", "") if isinstance(x, dict) else str(x))
    return out


def fleiss_kappa(items: list[tuple[int, int]]) -> float | None:
    """Fleiss' kappa for binary ratings: items as (yes votes, raters)."""
    items = [(y, n) for y, n in items if n > 1]
    if not items:
        return None
    n = items[0][1]
    if any(k != n for _, k in items):
        return None
    N = len(items)
    p_yes = sum(y for y, _ in items) / (N * n)
    p_no = 1 - p_yes
    pe = p_yes ** 2 + p_no ** 2
    p_i = [((y * y + (n - y) * (n - y)) - n) / (n * (n - 1)) for y, _ in items]
    pbar = sum(p_i) / N
    if pe == 1.0:
        return 1.0
    return (pbar - pe) / (1 - pe)


def vote_tool(tool: str, evals_by_judge: dict[str, dict]) -> dict:
    """{golden_url: voted row} for a tool from each judge's evaluations.json. A pull request missing from any judge
    is reported as incomplete and left out of the counts."""
    judges = list(evals_by_judge)
    urls = set()
    for ev in evals_by_judge.values():
        urls.update(url for url, rows in ev.items() if tool in rows)
    out: dict[str, dict] = {}
    for url in sorted(urls):
        rows = {j: (evals_by_judge[j].get(url) or {}).get(tool) for j in judges}
        missing = [j for j, r in rows.items() if r is None or r.get("skipped") or r.get("errors_count", 0) > 0]
        if missing:
            out[url] = {"tool": tool, "incomplete": True, "missing_judges": missing}
            continue
        goldens: dict[str, dict] = {}
        for r in rows.values():
            for x in r.get("true_positives", []) + r.get("false_negatives", []):
                goldens.setdefault(x.get("golden_comment", ""), {"severity": x.get("severity"), "category": x.get("category")})
        tp_by = {j: _tp_texts(r) for j, r in rows.items()}
        fp_by = {j: _fp_texts(r) for j, r in rows.items()}
        majority = (len(judges) // 2) + 1
        tps, fns, items = [], [], []
        for g, meta in goldens.items():
            yes = [j for j in judges if g in tp_by[j]]
            items.append((len(yes), len(judges)))
            if len(yes) >= majority:
                matched = next((x for j in yes for x in rows[j].get("true_positives", []) if x.get("golden_comment") == g), {})
                tps.append({"golden_comment": g, **meta, "matched_candidate": matched.get("matched_candidate"), "judges_yes": yes,
                            "confidence": matched.get("confidence")})
            else:
                fns.append({"golden_comment": g, **meta, "judges_yes": yes})
        candidates = set().union(*fp_by.values()) | {x.get("matched_candidate") for r in rows.values() for x in r.get("true_positives", []) if x.get("matched_candidate")}
        fps, cand_items = [], []
        for c in sorted(candidates):
            fp_votes = [j for j in judges if c in fp_by[j]]
            cand_items.append((len(fp_votes), len(judges)))
            if len(fp_votes) >= majority:
                fps.append({"candidate": c, "judges_fp": fp_votes})
        total_candidates = max(int(r.get("total_candidates", 0)) for r in rows.values())
        total_golden = len(goldens)
        tp, fp = len(tps), len(fps)
        out[url] = {
            "tool": tool, "incomplete": False, "repo_name": next((r.get("repo_name") for r in rows.values() if r.get("repo_name")), None),
            "true_positives": tps, "false_negatives": fns, "false_positives": fps,
            "tp": tp, "fp": fp, "fn": len(fns), "total_candidates": total_candidates, "total_golden": total_golden,
            "precision": tp / total_candidates if total_candidates else 0.0, "recall": tp / total_golden if total_golden else 0.0,
            "per_judge": {j: {"tp": r.get("tp", 0), "fp": r.get("fp", 0), "fn": r.get("fn", 0), "precision": r.get("precision"), "recall": r.get("recall")} for j, r in rows.items()},
            "agreement": {
                "golden_unanimous": sum(1 for y, n in items if y in (0, n)) / len(items) if items else None,
                "candidate_unanimous": sum(1 for y, n in cand_items if y in (0, n)) / len(cand_items) if cand_items else None,
                "golden_items": items, "candidate_items": cand_items,
            },
        }
    return out
