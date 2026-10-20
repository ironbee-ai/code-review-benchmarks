"""Health of a running pass, beyond API errors (to hear of problems as they happen, not at
the end): runs that errored, replies that were not the JSON asked for, salvaged or cut replies, runs made on another
route, parameters or provider pin, replies served by a provider outside the pin, configurations whose share of empty
reviews or findings per review moved far from repeat 1, very long calls, judge calls that failed and judge steps
that exited non-zero. Prints "health: no problems" or one line per problem, then notes.
Usage: python scripts/pass_health.py <repeat> <pass start, UTC, e.g. 2026-10-17T20:27>"""
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crbench.config import load_models, tier_params
from crbench.usage_log import read_rows

REP, SINCE = int(sys.argv[1]), sys.argv[2]
CUT = ("length", "max_tokens")
models = {m.id: m for m in load_models()}
problems, notes = [], []


def runs_of(rep):
    out = defaultdict(list)
    for p in glob.glob(str(ROOT / "results" / "runs" / "*" / "*" / f"*__r{rep}.json")):
        try:
            r = json.loads(Path(p).read_text())
        except ValueError:
            problems.append(f"unreadable run file {Path(p).name}")
            continue
        out[f"{r['model_id']}/{r['tier']}"].append(r)
    return out


now, base = runs_of(REP), runs_of(1)
for cfg, rs in sorted(now.items()):
    m = models.get(rs[0]["model_id"])
    for r in rs:
        tag = f"{cfg} {r['pr_id']}"
        if m is None or r.get("route") != m.route or r.get("params") != tier_params(m, r["tier"])[0] or r.get("provider_pin") != m.provider:
            problems.append(f"{tag}: made with another route, parameters or provider pin (will be redone)")
        st = r.get("status")
        if st == "error":
            problems.append(f"{tag}: error: {(r.get('error') or '')[:120]}")
        elif st == "parse_error":
            msg = f"{tag}: reply not the JSON asked for (finish {r.get('finish_reason')}, {len(r.get('calls') or [])} calls)"
            # unfinished after the extra calls allowed (7 in all), kept as empty reviews
            (notes if len(r.get("calls") or []) >= 7 else problems).append(msg + (", extra calls used up" if len(r.get("calls") or []) >= 7 else ""))
        if r.get("salvaged"):
            notes.append(f"{tag}: findings salvaged from a reply with broken JSON")
        if st == "ok" and r.get("finish_reason") in CUT:
            problems.append(f"{tag}: last reply cut at the output cap")
        pin = (m.provider or {}).get("order") if m and m.provider else None
        served = (r.get("provider_served") or "")
        norm = lambda x: re.sub(r"[^a-z0-9]", "", x.lower())     # "Google AI Studio" = "google-ai-studio", "Z.AI" = "z-ai"
        if pin and served and not any(norm(p.split("/")[0]) in norm(served) for p in pin):
            problems.append(f"{tag}: served by {served}, outside the pin {pin}")
        if (r.get("latency_ms") or 0) > 40 * 60 * 1000:
            notes.append(f"{tag}: call took {r['latency_ms'] / 60000:.0f} min")
    done = [r for r in rs if r.get("status") in ("ok", "parse_error")]
    ref = [r for r in base.get(cfg, []) if r.get("status") in ("ok", "parse_error")]
    if len(done) >= 15 and ref:
        prs = {r["pr_id"] for r in done}
        ref = [r for r in ref if r["pr_id"] in prs]
        e_now = sum(1 for r in done if not r.get("findings")) / len(done)
        e_ref = sum(1 for r in ref if not r.get("findings")) / max(len(ref), 1)
        f_now = sum(len(r.get("findings") or []) for r in done) / len(done)
        f_ref = sum(len(r.get("findings") or []) for r in ref) / max(len(ref), 1)
        if e_now - e_ref > 0.2 and e_now * len(done) >= 5:
            problems.append(f"{cfg}: {e_now:.0%} empty reviews against {e_ref:.0%} in repeat 1 on the same PRs")
        if f_ref and not 0.5 <= f_now / f_ref <= 2:
            problems.append(f"{cfg}: {f_now:.1f} findings per review against {f_ref:.1f} in repeat 1 on the same PRs")
    multi = sum(1 for r in rs if len(r.get("calls") or []) > 1)
    fa = lambda x: x if isinstance(x, int) else len(x or [])      # failed attempts sit on the run and on each call
    failed = sum(fa(r.get("failed_attempts")) + sum(fa(c.get("failed_attempts")) for c in r.get("calls") or []) for r in rs)
    for r in rs:
        for c in r.get("calls") or []:
            for f in c.get("failed_attempts") or [] if not isinstance(c.get("failed_attempts"), int) else []:
                if "timeout" in str(f.get("error", "")):
                    notes.append(f"{cfg} {r['pr_id']}: an attempt timed out after {f.get('seconds', 0) / 60:.0f} min and was retried")
    if multi or failed:
        notes.append(f"{cfg}: {multi} runs needed more than one call, {failed} failed attempts retried")

bad, calls = Counter(), Counter()
first_err = {}
KNOWN_JUNK: dict[str, int] = {}     # judge id -> broken lines already known in its log (none in a clean log)
for p in glob.glob(str(ROOT / "results" / "judge_usage" / "*.jsonl")):
    rows, junk = read_rows(p)
    if junk > KNOWN_JUNK.get(Path(p).stem, 0):
        problems.append(f"judge log {Path(p).name}: {junk} lines that are not JSON (known before: {KNOWN_JUNK.get(Path(p).stem, 0)})")
    for row in rows:
        if row.get("ts", "") < SINCE or row.get("step") == "probe":
            continue
        calls[row["judge"]] += 1
        if row.get("status") != 200:
            bad[row["judge"]] += 1
            first_err.setdefault(row["judge"], str(row.get("error") or row.get("status"))[:100])
for j, n in bad.items():   # ~0.2-0.7% "Bad file descriptor" is the known proxy race (fixed before pass 3); above 2% is a problem
    (problems if n / calls[j] > 0.02 else notes).append(f"judge {j}: {n} of {calls[j]} calls failed ({100 * n / calls[j]:.1f}%, retried by the step); "
                                                        f"first: {first_err[j][:70]}")

# files the judging process writes, which a misdirected socket write could corrupt (the proxy fault): judged records of this
# repeat and the lanes' JSON (a step that dies mid-write is restored from its copy by the next judging run)
for p in glob.glob(str(ROOT / "results" / "judged" / f"*__r{REP}.json")) + glob.glob(str(ROOT / "work" / "lanes" / "**" / "*.json"), recursive=True):
    try:
        json.loads(Path(p).read_bytes())
    except (ValueError, UnicodeDecodeError) as e:
        problems.append(f"unparseable JSON: {Path(p).relative_to(ROOT)} ({str(e)[:60]})")

log = ROOT / "results" / f"pass_r{REP}" / "judge.log"
if log.exists():
    fails = [ln.strip() for ln in log.read_text().splitlines() if re.search(r": exit [1-9]\d* in ", ln)]
    for ln in fails[-5:]:
        m = re.search(r"step\w* (\S+__r\d+): exit", ln)
        rec = ROOT / "results" / "judged" / f"{m.group(1)}.json" if m else None
        done = False
        if rec is not None and rec.exists():          # judged again since, with every pull request complete
            v = json.loads(rec.read_bytes()).get("voted") or {}
            done = bool(v) and not any(x.get("incomplete") for x in v.values())
        (notes if done else problems).append(f"judge step failed{' (since judged in full)' if done else ''}: {ln[:150]}")

print("health: no problems" if not problems else "\n".join(f"PROBLEM {p}" for p in problems))
keep = [n for n in notes if "timed out" in n or "took" in n or "extra calls" in n]     # always shown
for n in keep + [n for n in notes if n not in keep][-12:]:
    print(f"note {n}")
