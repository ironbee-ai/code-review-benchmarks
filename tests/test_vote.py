from crbench.vote import fleiss_kappa, vote_tool


def row(tps, fns, fps, total):
    return {"true_positives": [{"golden_comment": g, "category": "bug", "severity": "High", "matched_candidate": c} for g, c in tps],
            "false_negatives": [{"golden_comment": g, "category": "bug", "severity": "High"} for g in fns],
            "false_positives": [{"candidate": c} for c in fps], "total_candidates": total, "errors_count": 0}


def test_majority():
    evals = {
        "j1": {"u": {"t": row([("g1", "c1")], ["g2"], ["c2"], 2)}},
        "j2": {"u": {"t": row([("g1", "c1"), ("g2", "c2")], [], [], 2)}},
        "j3": {"u": {"t": row([], ["g1", "g2"], ["c1", "c2"], 2)}},
    }
    v = vote_tool("t", evals)["u"]
    assert v["tp"] == 1 and v["fn"] == 1 and v["fp"] == 1
    assert v["true_positives"][0]["golden_comment"] == "g1" and sorted(v["true_positives"][0]["judges_yes"]) == ["j1", "j2"]
    assert v["false_positives"][0]["candidate"] == "c2"
    assert v["precision"] == 0.5 and v["recall"] == 0.5


def test_incomplete_when_a_judge_is_missing():
    evals = {"j1": {"u": {"t": row([], ["g1"], [], 0)}}, "j2": {}, "j3": {"u": {"t": row([], ["g1"], [], 0)}}}
    v = vote_tool("t", evals)["u"]
    assert v["incomplete"] and v["missing_judges"] == ["j2"]


def test_kappa():
    assert fleiss_kappa([(3, 3), (0, 3), (3, 3), (0, 3)]) == 1.0
    assert fleiss_kappa([]) is None
    k = fleiss_kappa([(2, 3), (1, 3), (3, 3), (0, 3)])
    assert -1 <= k <= 1
