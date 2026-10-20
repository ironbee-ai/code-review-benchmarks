"""The tools on the benchmark site's offline leaderboard, judged by our panel (Gemini, Sol, Opus; Grok in place of a
judge of the tool's own family; dedup by the first, majority vote), the same steps that judged our models. Candidates
are the ones the site's default judge, Claude Opus 4.5, extracted (results/anthropic_claude-opus-4-5-20251101/
candidates.json in the benchmark), so only the verdict changes. gitar-v2 is on the site but not in the benchmark's
repository: its review PRs are fetched from GitHub with the benchmark's own step 1 code and extracted with Opus 4.5
on Bedrock and the benchmark's own step 2 prompt. Everything goes to results/products/.
Usage: python scripts/site_products.py fetch | extract | judge | score"""
import importlib.util
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crbench.env import load_env, region, require

M = ROOT / "work" / "martian" / "offline"
OUT = ROOT / "results" / "products"
SITE_JUDGE = "anthropic_claude-opus-4-5-20251101"   # the site's default judge, whose candidates we use
DASHBOARD = ROOT / "data" / "martian" / "benchmark_dashboard_2026-09-08.json"


def read_json(path):
    return json.loads(Path(path).read_text())
TOOLS = ["augment", "baz", "bugbot", "claude", "claude-code", "codeant-v2", "coderabbit", "copilot-v2", "cubic-v2", "devin",
         "gemini-v2", "gitar-v2", "gitlab", "graphite", "greptile-v4-1", "kg", "kodus-v2", "macroscope", "qodo-extended-v2",
         "qodo-v2", "sourcery"]
FAMILY = {"claude": "anthropic", "claude-code": "anthropic", "gemini-v2": "google"}   # no judge of the tool's own family
FETCHED = "gitar-v2"
EXTRACTOR = "global.anthropic.claude-opus-4-5-20251101-v1:0"
EXTRACTOR_PRICE = {"input": 5.00, "output": 25.00}


def module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch() -> None:
    """gitar-v2's 50 review PRs, with the benchmark's step 1 functions (bot comments: inline, review bodies, issue comments)."""
    s1 = module(M / "code_review_benchmark" / "step1_download_prs.py", "step1")
    golden = s1.load_golden_comments(str(M / "golden_comments"))
    repos = s1.gh(["repo", "list", "code-review-benchmark", "--limit", "5000", "--json", "name"])
    picked = []
    for r in repos:
        p = s1.parse_repo_name(r["name"])
        if p and p["tool"] == FETCHED:
            picked.append((r["name"], s1.find_golden_url(golden, p["original_repo"], p["pr_number"])))
    print(f"{len(repos)} repos, {len(picked)} for {FETCHED}", flush=True)
    urls = {e["golden_url"] for e in read_json(ROOT / "data" / "sets" / "full.json")}
    assert all(u in urls for _, u in picked) and len({u for _, u in picked}) == len(picked) == 50, "expected one repo per PR"
    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(lambda x: (x[1], s1.fetch_repo_data("code-review-benchmark", x[0], tool=FETCHED)), picked))
    out = {u: {"tool": FETCHED, "repo_name": d["repo_name"], "pr_url": d["pr_meta"]["url"], "review_comments": d["comments"]} for u, d in got}
    (OUT / FETCHED).mkdir(parents=True, exist_ok=True)
    (OUT / FETCHED / "reviews.json").write_text(json.dumps(out, indent=1))
    print(f"{sum(len(v['review_comments']) for v in out.values())} comments; "
          f"{sum(1 for v in out.values() if not v['review_comments'])} PRs without any", flush=True)


def extract() -> None:
    """Opus 4.5 (Bedrock InvokeModel) with the benchmark's step 2: one call per review, all comment bodies joined,
    temperature 0, its system prompt and parsing; a review under 20 characters gets no candidates."""
    import httpx
    load_env()
    s2 = module(M / "code_review_benchmark" / "step2_extract_comments.py", "step2")
    reviews = read_json(OUT / FETCHED / "reviews.json")
    url_ = f"https://bedrock-runtime.{region()}.amazonaws.com/model/{EXTRACTOR}/invoke"
    headers = {"Authorization": f"Bearer {require('AWS_BEARER_TOKEN_BEDROCK')}", "Content-Type": "application/json"}
    usage_path, usage_lock = OUT / FETCHED / "extract_usage.jsonl", threading.Lock()

    def log(row):
        with usage_lock, open(usage_path, "a") as f:
            f.write(json.dumps(row) + "\n")

    def one(item):
        golden_url, review = item
        text = s2.get_all_comment_text(review["review_comments"])
        if not text or len(text.strip()) < 20:
            return golden_url, None
        body = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 16000, "temperature": 0.0,
                "system": "You extract code review issues from comments. Always respond with valid JSON.",
                "messages": [{"role": "user", "content": s2.EXTRACT_PROMPT.format(comment=text)}]}
        for attempt in range(6):
            with httpx.Client(timeout=300) as c:
                r = c.post(url_, headers=headers, json=body)
            row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "golden_url": golden_url, "status": r.status_code, "attempt": attempt + 1}
            if r.status_code != 200:
                row["error"] = r.text[:300]
                log(row)
                time.sleep(2 ** attempt)
                continue
            msg = r.json()
            row.update(usage=msg.get("usage"), stop_reason=msg.get("stop_reason"))
            log(row)
            content = "".join(b.get("text", "") for b in msg["content"] if b.get("type") == "text").strip()
            if content.startswith("```"):                       # the step's own fence stripping
                content = content.split("```")[1]
                content = content.removeprefix("json")
                content = content.strip()
            try:
                issues = json.loads(content)["issues"]
            except (json.JSONDecodeError, KeyError, TypeError):
                if attempt >= 2:                                 # the step's three tries at a parse
                    raise SystemExit(f"{golden_url}: reply did not parse after 3 tries")
                continue
            return golden_url, [{"text": i, "path": None, "line": None, "source": "extracted"} for i in issues]
        raise SystemExit(f"{golden_url}: no reply after 6 tries")

    with ThreadPoolExecutor(10) as ex:
        got = list(ex.map(one, reviews.items()))
    cands = {u: {FETCHED: c} for u, c in got if c is not None}
    (OUT / FETCHED / "candidates.json").write_text(json.dumps(cands, indent=1))
    rows = [json.loads(x) for x in usage_path.read_text().splitlines() if x.strip()]
    cost = sum((r["usage"]["input_tokens"] * EXTRACTOR_PRICE["input"] + r["usage"]["output_tokens"] * EXTRACTOR_PRICE["output"]) / 1e6
               for r in rows if r.get("usage"))
    print(f"{len(cands)} reviews extracted, {sum(len(c[FETCHED]) for c in cands.values())} candidates, "
          f"{sum(1 for r in rows if r['status'] != 200)} failed calls, stop reasons "
          f"{sorted({r.get('stop_reason') for r in rows if r.get('usage')})}, ${cost:.2f}", flush=True)


def runs_for(tool: str, cands: dict, prs: list[dict]) -> list[dict]:
    """One run per PR of the set (50), as on the site; a PR with no candidates has no findings."""
    rid = f"site-{tool}__default__r1"
    return [{"run_id": f"{rid}@{p['id']}", "pr_id": p["id"], "golden_url": p["golden_url"], "status": "ok",
             "findings": [{"title": "", "body": c["text"], "file": c.get("path"), "line": c.get("line")}
                          for c in (cands.get(p["golden_url"]) or {}).get(tool) or []]} for p in prs]


def judge(only: list[str]) -> None:
    from crbench import judge as J
    from crbench import judge_proxy as JP
    from crbench.config import Model, load_judges
    from crbench.dataset import load_set
    load_env()
    J.JUDGED = OUT / "judged"
    JP.USAGE_DIR = OUT / "judge_usage"
    JP.USAGE_DIR.mkdir(parents=True, exist_ok=True)
    prs = load_set(ROOT / "data" / "sets" / "full.json")
    theirs = read_json(M / "results" / SITE_JUDGE / "candidates.json")
    fetched = read_json(OUT / FETCHED / "candidates.json")
    tools, runs_by_tool, models = [], {}, {}
    for t in only or TOOLS:
        mid = f"site-{t}"
        models[mid] = Model(id=mid, family=FAMILY.get(t, "product"), route="none", model="-", tiers={"default": {}}, sets=[])
        tools.append(f"{mid}__default__r1")
        runs_by_tool[tools[-1]] = runs_for(t, fetched if t == FETCHED else theirs, prs)
        print(f"{t}: {sum(len(r['findings']) for r in runs_by_tool[tools[-1]])} candidates", flush=True)
    J.judge_tools(tools, runs_by_tool, models, load_judges(), shards=8)


def site_scores() -> dict:
    """The site's own numbers: core profile counts per PR from its dashboard data, for each of its judges."""
    d = read_json(DASHBOARD)
    out = {}
    for jm, v in d["models"].items():
        for pr in v["prs"]:
            for t, m in pr["tool_metrics"].items():
                c = out.setdefault(jm, {}).setdefault(t, {"tp": 0, "fp": 0, "fn": 0})
                for k in c:
                    c[k] += m["core"][k]
    return out


def site_scores_f2(c: dict, beta: float = 2.0) -> float:
    p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
    r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
    return (1 + beta ** 2) * p * r / (beta ** 2 * p + r) if p + r else 0.0


def score() -> None:
    from crbench.metrics import golden_lookup
    from crbench.metrics import score as score_records
    lookup = golden_lookup()
    site = site_scores()
    names = read_json(DASHBOARD)["tool_display_names"]

    def f(tp, fp, fn, beta=2.0):
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        return p, r, ((1 + beta ** 2) * p * r / (beta ** 2 * p + r) if p + r else 0.0)

    summary = {}
    for t in TOOLS:
        rec = read_json(OUT / "judged" / f"site-{t}__default__r1.json")
        mine = score_records(rec["voted"], "core", 2.0, lookup, ci=True)
        per_judge = {j: score_records(rows, "core", 2.0, lookup, ci=False)["fbeta"] for j, rows in rec["per_judge"].items()}
        theirs = {jm: dict(zip(("precision", "recall", "fbeta"), f(**c[t])), **c[t]) for jm, c in site.items() if t in c}
        summary[t] = {"name": names.get(t, t), "ours": {k: mine[k] for k in mine if k in ("precision", "recall", "f1", "fbeta", "tp", "fp", "fn", "ci")},
                      "our_judges_alone_f2": per_judge, "site": theirs}
        o, s = mine, theirs.get(SITE_JUDGE, {})
        print(f"{names.get(t, t):24s} ours F2 {100 * o['fbeta']:5.1f} (P {100 * o['precision']:5.1f} R {100 * o['recall']:5.1f}) | "
              f"site Opus 4.5 F2 {100 * s.get('fbeta', 0):5.1f} (P {100 * s.get('precision', 0):5.1f} R {100 * s.get('recall', 0):5.1f})", flush=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "judge":
        judge(sys.argv[2:])
    else:
        {"fetch": fetch, "extract": extract, "score": score}[sys.argv[1]]()
