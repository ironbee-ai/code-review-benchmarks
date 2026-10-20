"""Watches a running pass and exits with a message as soon as something needs attention, so a waiting caller is told:
OpenRouter credit low, new errored runs (or any 402 / insufficient credit), no run finished for a while, judge steps
failing, or the pass ending. Usage: python scripts/watch_pass.py <repeats> [--credit-floor 15] [--stall-minutes 45]
Never prints a key."""
import argparse
import glob
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import httpx

from crbench.env import load_env

ap = argparse.ArgumentParser()
ap.add_argument("repeats")
ap.add_argument("--credit-floor", type=float, default=15.0)
ap.add_argument("--stall-minutes", type=float, default=45.0)
ap.add_argument("--every", type=float, default=120.0, help="seconds between checks")
ap.add_argument("--since", default=time.strftime("%Y-%m-%dT%H:%M", time.gmtime()), help="pass start (UTC), for what was billed during it")
args = ap.parse_args()
load_env()
LOG = ROOT / "results" / f"pass_r{args.repeats}"
reps = {int(x) for x in re.findall(r"\d+", args.repeats)}
if "-" in args.repeats:
    a, b = (int(x) for x in args.repeats.split("-"))
    reps = set(range(a, b + 1))


def credit_left() -> float | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        d = httpx.get("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {key}"}, timeout=20).json()["data"]
        return d["total_credits"] - d["total_usage"]
    except Exception:  # noqa: BLE001
        return None


def runs() -> tuple[dict, float]:
    errors, newest = {}, 0.0
    for p in glob.glob(str(ROOT / "results" / "runs" / "*" / "*" / "*.json")):
        m = re.search(r"__r(\d+)\.json$", p)
        if not m or int(m.group(1)) not in reps:
            continue
        newest = max(newest, os.path.getmtime(p))
        try:
            with open(p) as f:
                r = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if r.get("status") == "error":
            errors[f"{r['model_id']}/{r['tier']}/{r.get('pr_id')}"] = (r.get("error") or "")[:160]
    return errors, newest


def pass_running() -> bool:
    pid_file = ROOT / "results" / f"pass_r{args.repeats}.pid"
    try:
        os.kill(int(pid_file.read_text().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def still_needed() -> str:
    try:
        from openrouter_need import need
        n = need(sorted(reps), args.since)
        return f"still to bill ~${n['total_left']:.0f} (reviews ~${n['reviews_left']:.0f}, Gemini judge ~${n['gemini_judge_left']:.0f})"
    except Exception as e:  # noqa: BLE001
        return f"(projection failed: {e})"


sys.path.insert(0, str(ROOT / "scripts"))
base_errors, _ = runs()
checks = 0
judge_log = LOG / "judge.log"
judge_seen = judge_log.stat().st_size if judge_log.exists() else 0
start = time.time()
while True:
    time.sleep(args.every)
    if not pass_running():
        print("PASS ENDED:", (LOG / "pass.log").read_text().splitlines()[-1] if (LOG / "pass.log").exists() else "")
        break
    left = credit_left()
    checks += 1
    if left is not None:
        projection = still_needed() if checks % 10 == 1 or left < args.credit_floor else ""
        with open(LOG / "credit.log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} OpenRouter credit left ${left:.2f} {projection}\n")
    if left is not None and left < args.credit_floor:
        print(f"OPENROUTER CREDIT LOW: ${left:.2f} left; {projection}")
        break
    errors, newest = runs()
    new = {k: v for k, v in errors.items() if k not in base_errors}
    if any("402" in v or "credit" in v.lower() for v in new.values()):
        print("OPENROUTER OUT OF CREDIT:", next(v for v in new.values() if "402" in v or "credit" in v.lower()))
        break
    if len(new) >= 5:
        print(f"{len(new)} NEW ERRORED RUNS:", json.dumps(dict(list(new.items())[:8]), indent=1))
        break
    if newest and time.time() - newest > args.stall_minutes * 60 and time.time() - start > args.stall_minutes * 60:
        print(f"STALL: no run finished for {(time.time() - newest) / 60:.0f} minutes")
        break
    if judge_log.exists() and judge_log.stat().st_size > judge_seen:
        with open(judge_log) as f:
            f.seek(judge_seen)
            chunk = f.read()
        judge_seen = judge_log.stat().st_size
        bad = [ln for ln in chunk.splitlines() if "stderr:" in ln or "Traceback" in ln or "unfinished after pass 3" in ln]
        if len(bad) >= 3:
            print("JUDGE STEPS FAILING:", "\n".join(bad[:6]))
            break
