"""Judging: the benchmark's own steps (dedup, judge), unmodified, run in lanes with their endpoint pointed at the
local judge proxy. A tool is judged by the first three pool judges outside its model's family. Its dedup groups are
made once, by the first of the three, and given to the other two, so the three judge the same candidates against the
same groups; the three judges' rows are then voted (vote.py)."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import Judge, JudgePool, Model, judges_for, observers_for, parse_tool_name
from .env import ROOT
from .judge_proxy import JudgeProxy
from .lane import (
    assign_shards,
    clear_tool,
    dedup_groups,
    evaluations,
    inject,
    judged_runs,
    lane_dir,
    prepare_lane,
    put_dedup_groups,
    restore_broken,
    snapshot,
)
from .vote import vote_tool

JUDGED = ROOT / "results" / "judged"
MAX_PASSES = 3
SECRET_VARS = ("AWS_BEARER_TOKEN_BEDROCK", "OPENROUTER_API_KEY", "GITHUB_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
_print_lock = threading.Lock()
_stop = threading.Event()                 # set on Ctrl-C or SIGTERM: no new step starts
_active: set[subprocess.Popen] = set()    # the steps running now
_active_lock = threading.Lock()
STEP_MODULES = ("code_review_benchmark.step2_5_dedup_candidates", "code_review_benchmark.step3_judge_comments")


def _log(msg: str) -> None:
    with _print_lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def martian_env(lane: Path, judge: Judge, base_url: str) -> dict:
    """The steps' environment: no provider key at all (the proxy holds them), the proxy as their endpoint."""
    env = {k: v for k, v in os.environ.items() if k not in SECRET_VARS}
    env.update({"MARTIAN_API_KEY": "crbench-proxy", "MARTIAN_BASE_URL": base_url, "MARTIAN_MODEL": judge.model, "PYTHONPATH": str(lane)})
    return env


def run_step(proxy: JudgeProxy, judge: Judge, lane: Path, module: str, tool: str, extra: list[str], log) -> int:
    if _stop.is_set():
        return 130
    t0 = time.time()
    step = module.split("_", 1)[0]
    snapshot(lane, judge)
    proc = subprocess.Popen([sys.executable, "-m", f"code_review_benchmark.{module}", "--tool", tool, *extra], cwd=lane,
                            env=martian_env(lane, judge, proxy.base_url(judge.id, step, tool)), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    with _active_lock:
        _active.add(proc)
    try:
        out, err = proc.communicate()
    finally:
        with _active_lock:
            _active.discard(proc)
    restored = restore_broken(lane, judge)
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    log(f"[{judge.id}] {module} {tool}: exit {proc.returncode} in {time.time() - t0:.0f}s{(': ' + lines[-1][:140]) if lines else ''}")
    if restored:
        log(f"[{judge.id}] {tool}: {', '.join(restored)} was cut short by the interruption; restored from the copy taken before the step")
    if proc.returncode != 0 and not _stop.is_set():
        log(f"[{judge.id}] stderr: {err.strip()[-800:]}")
    return proc.returncode


def steps_running() -> list[str]:
    """Benchmark steps still running on this machine (left over from a judging pass that was killed)."""
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False).stdout
    return [ln.strip() for ln in out.splitlines() if any(m in ln for m in STEP_MODULES)]


def _in_lanes(fn, keys: list) -> None:
    """fn over the lanes, one thread each. On Ctrl-C (or SIGTERM): no new step starts, the running ones are stopped,
    and the interruption goes on up; a rerun resumes from what the steps saved."""
    with ThreadPoolExecutor(max_workers=max(1, len(keys))) as ex:
        try:
            list(ex.map(fn, keys))
        except KeyboardInterrupt:
            _stop.set()
            with _active_lock:
                for p in _active:
                    p.terminate()
            raise


def _sigterm(signum, frame):
    raise KeyboardInterrupt


def unfinished(ev: dict, tool: str, expected: set[str]) -> list[str]:
    return [url for url in expected if (row := (ev.get(url) or {}).get(tool)) is None or row.get("errors_count", 0) > 0]


def plan(tools: list[str], models_by_id: dict[str, Model], pool: JudgePool) -> tuple[dict[str, list[Judge]], dict[str, Judge], dict[str, list[Judge]]]:
    """Per tool: its voting triple and its observers; and every judge involved."""
    triples = {t: judges_for(models_by_id[parse_tool_name(t)[0]].family, pool) for t in tools}
    observers = {t: observers_for(models_by_id[parse_tool_name(t)[0]].family, pool) for t in tools}
    judges = {j.id: j for t in tools for j in triples[t] + observers[t]}
    return triples, judges, observers


def judge_tools(tools: list[str], runs_by_tool: dict[str, list[dict]], models_by_id: dict[str, Model], pool: JudgePool,
                shards: int = 4, force: bool = False, log=_log) -> dict[str, dict]:
    left = steps_running()
    if left:
        raise SystemExit("benchmark steps from an earlier judging pass are still running; wait for them or stop them:\n  " + "\n  ".join(left))
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _sigterm)
    _stop.clear()
    triples, judges, observers = plan(tools, models_by_id, pool)
    everyone = {t: triples[t] + observers[t] for t in tools}  # the voting triple, then the observers
    where: dict[tuple[str, str], int] = {}                    # (judge id, tool) -> shard
    for jid, judge in judges.items():
        mine = [t for t in tools if any(j.id == jid for j in everyone[t])]
        for tool, shard in assign_shards(judge, mine, shards).items():
            where[(jid, tool)] = shard
    for (jid, tool), shard in sorted(where.items()):
        judge = judges[jid]
        lane = prepare_lane(judge, shard)
        for name in restore_broken(lane, judge):
            log(f"[{jid}] lane {shard}: {name} did not parse (a step was killed while saving); restored from its copy")
        if force:
            clear_tool(lane, judge, tool)
        inject(lane, judge, tool, runs_by_tool[tool])
    log(f"{len(tools)} tools, {len(judges)} judges, {len({(j, s) for (j, _), s in where.items()})} lanes")

    def lane_queue(phase: str) -> dict[tuple[str, int], list[str]]:
        q: dict[tuple[str, int], list[str]] = {}
        for tool in tools:
            for j in (triples[tool][:1] if phase == "dedup" else everyone[tool]):
                q.setdefault((j.id, where[(j.id, tool)]), []).append(tool)
        return q

    with JudgeProxy(judges) as proxy:
        log(f"judge proxy on 127.0.0.1:{proxy.port}")

        def dedup_lane(key: tuple[str, int]) -> None:
            jid, shard = key
            judge = judges[jid]
            for tool in queue[key]:
                run_step(proxy, judge, lane_dir(judge, shard), "step2_5_dedup_candidates", tool, ["--force"] if force else [], log)

        queue = lane_queue("dedup")
        _in_lanes(dedup_lane, list(queue))
        # the first judge's groups to the others (after every dedup has finished: no lane is being written now)
        for tool, triple in triples.items():
            first = triple[0]
            groups = dedup_groups(lane_dir(first, where[(first.id, tool)]), first, tool)
            for other in everyone[tool][1:]:
                put_dedup_groups(lane_dir(other, where[(other.id, tool)]), other, tool, groups)

        def judge_lane(key: tuple[str, int]) -> None:
            jid, shard = key
            judge = judges[jid]
            lane = lane_dir(judge, shard)
            for tool in queue[key]:
                expected = {r["golden_url"] for r in judged_runs(runs_by_tool[tool])}
                for attempt in range(1, MAX_PASSES + 1):
                    if _stop.is_set():
                        return
                    run_step(proxy, judge, lane, "step3_judge_comments", tool, [], log)
                    left = unfinished(evaluations(lane, judge), tool, expected)
                    if not left:
                        break
                    log(f"[{jid}] {tool}: {len(left)} pull requests unfinished after pass {attempt}")

        queue = lane_queue("judge")
        _in_lanes(judge_lane, list(queue))

    JUDGED.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    for tool, triple in triples.items():
        evals = {j.id: evaluations(lane_dir(j, where[(j.id, tool)]), j) for j in triple}
        obs = {j.id: evaluations(lane_dir(j, where[(j.id, tool)]), j) for j in observers[tool]}
        describe = lambda js: [{"id": j.id, "family": j.family, "model": j.model, "route": j.route, "params": j.params} for j in js]
        record = {"tool": tool, "judges": describe(triple), "observers": describe(observers[tool]),
                  "dedup_judge": triple[0].id, "voted": vote_tool(tool, evals),
                  "per_judge": {j.id: {url: rows[tool] for url, rows in evals[j.id].items() if tool in rows} for j in triple},
                  "per_observer": {jid: {url: rows[tool] for url, rows in ev.items() if tool in rows} for jid, ev in obs.items()},
                  "dedup_groups": dedup_groups(lane_dir(triple[0], where[(triple[0].id, tool)]), triple[0], tool),
                  "judged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        tmp = JUDGED / f"{tool}.json.tmp"
        with open(tmp, "w") as f:
            json.dump(record, f, indent=1)
        tmp.replace(JUDGED / f"{tool}.json")
        out[tool] = record
    return out


def load_judged(tool: str) -> dict | None:
    path = JUDGED / f"{tool}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def judge_calls_estimate(runs: list[dict], golden_counts: dict[str, int]) -> int:
    """The match calls one judge makes for a tool: goldens x candidates per pull request (the benchmark's step 3)."""
    return sum(golden_counts.get(r["golden_url"], 0) * len(r.get("findings", [])) for r in judged_runs(runs))
