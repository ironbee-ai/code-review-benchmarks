"""A lane is a private copy of the benchmark's offline directory (work/lanes/<judge>/<shard>/offline). The benchmark's
steps read and write whole JSON files, so one lane runs one step at a time; a judge has several lanes (shards) to
judge several tools at once. Our runs enter a lane in the benchmark's own formats: a review per (pull request, tool)
in results/benchmark_data.json, and the candidates (one per finding, text = title + body) in
results/<judge model dir>/candidates.json. A tool stays in the shard that first took it, so a rerun resumes there."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .config import Judge
from .dataset import WORK, martian_offline
from .prompt import finding_text

LANES = WORK / "lanes"
IGNORED = shutil.ignore_patterns(".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "anthropic_*", "openai_*", "*.xlsx")
JUDGE_FILES = ("candidates.json", "dedup_groups.json", "evaluations.json")
# The benchmark's judging step gives one review 30 minutes (REVIEW_TIMEOUT = 1800) and drops a review that takes
# longer. A review with hundreds of findings needs more of a slow judge (538 findings: ~36 minutes), so lanes allow 90.
# A review that finishes within 30 minutes gets the same verdicts either way.
REVIEW_TIMEOUT_S = 5400


def lane_dir(judge: Judge, shard: int) -> Path:
    return LANES / judge.id / str(shard) / "offline"


def prepare_lane(judge: Judge, shard: int) -> Path:
    """A fresh lane holds the benchmark's code and its pull requests with their golden comments, but none of the
    leaderboard tools' reviews: the steps only ever see our tools, and read a small file."""
    lane = lane_dir(judge, shard)
    if not lane.exists():
        lane.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(martian_offline(), lane, ignore=IGNORED)
        bench = _read(lane / "results" / "benchmark_data.json")
        for entry in bench.values():
            entry["reviews"] = []
        _write(lane / "results" / "benchmark_data.json", bench)
        for name in ("pr_labels.json",):
            (lane / "results" / name).unlink(missing_ok=True)
    _set_review_timeout(lane)
    (lane / "results" / judge.model_dir).mkdir(parents=True, exist_ok=True)
    return lane


def _set_review_timeout(lane: Path) -> None:
    step = lane / "code_review_benchmark" / "step3_judge_comments.py"
    text = step.read_text()
    lines = text.splitlines(keepends=True)
    hits = [i for i, ln in enumerate(lines) if ln.startswith("REVIEW_TIMEOUT = ")]
    if len(hits) != 1:
        raise SystemExit(f"{step}: expected one REVIEW_TIMEOUT line, found {len(hits)}")
    want = f"REVIEW_TIMEOUT = {REVIEW_TIMEOUT_S}  # crbench: the benchmark's 1800 s is too short for the longest reviews\n"
    if lines[hits[0]] != want:
        lines[hits[0]] = want
        step.write_text("".join(lines))


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    tmp.replace(path)


STEP_FILES = ("dedup_groups.json", "evaluations.json")  # the files the benchmark's steps rewrite in place


def _parses(path: Path) -> bool:
    try:
        _read(path)
        return True
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False


def snapshot(lane: Path, judge: Judge) -> None:
    """Copies of the files a step rewrites, taken before it runs: the benchmark writes them in place, so a step
    interrupted while saving leaves a file cut short. restore_broken() puts the copy back."""
    for name in STEP_FILES:
        path = lane / "results" / judge.model_dir / name
        if path.exists() and _parses(path):
            shutil.copyfile(path, path.with_suffix(".json.bak"))


def restore_broken(lane: Path, judge: Judge) -> list[str]:
    """Restores every step file that does not parse from its copy (the rows the interrupted step added are made again
    by the next pass). Returns the restored file names."""
    restored = []
    for name in STEP_FILES:
        path = lane / "results" / judge.model_dir / name
        if path.exists() and not _parses(path):
            backup = path.with_suffix(".json.bak")
            if not backup.exists():
                raise RuntimeError(f"{path} does not parse and has no copy to restore")
            shutil.copyfile(backup, path)
            restored.append(name)
    return restored


def _tools_in(lane: Path, judge: Judge) -> set[str]:
    tools: set[str] = set()
    for name in ("candidates.json", "evaluations.json"):
        for rows in _read(lane / "results" / judge.model_dir / name).values():
            if isinstance(rows, dict):
                tools.update(rows)
    return tools


def assign_shards(judge: Judge, tools: list[str], shards: int) -> dict[str, int]:
    """A tool goes to the shard that already holds it, else to the least loaded shard."""
    held: dict[int, set[str]] = {k: _tools_in(lane_dir(judge, k), judge) for k in range(shards)}
    load = {k: 0 for k in range(shards)}
    out: dict[str, int] = {}
    for tool in sorted(tools):
        k = next((k for k in range(shards) if tool in held[k]), None)
        if k is None:
            k = min(load, key=lambda s: (load[s], s))
        out[tool] = k
        load[k] += 1
    return out


def review_of(tool: str, run: dict) -> dict:
    comments = [{"path": f.get("file") or "", "line": f.get("line"), "body": finding_text(f)} for f in run.get("findings", [])]
    return {"tool": tool, "repo_name": run["pr_id"], "pr_url": run.get("golden_url"), "review_comments": comments, "run_id": run.get("run_id")}


def candidates_of(run: dict) -> list[dict]:
    return [{"text": finding_text(f), "path": f.get("file") or None, "line": f.get("line"), "source": "direct"} for f in run.get("findings", [])
            if finding_text(f).strip()]


def judged_runs(runs: list[dict]) -> list[dict]:
    """The runs a judge sees: those that produced a reply (a reply that was not JSON counts as a review with no findings)."""
    return [r for r in runs if r.get("status") in ("ok", "parse_error")]


def inject(lane: Path, judge: Judge, tool: str, runs: list[dict]) -> int:
    """The tool's runs become its reviews in the lane's benchmark_data.json (replacing earlier ones) and its
    candidates in the judge's candidates.json. Returns the number of reviews."""
    path = lane / "results" / "benchmark_data.json"
    bench = _read(path)
    by_url = {r["golden_url"]: r for r in judged_runs(runs)}
    n = 0
    for golden_url, entry in bench.items():
        entry["reviews"] = [rv for rv in entry.get("reviews", []) if rv.get("tool") != tool]
        if golden_url in by_url:
            entry["reviews"].append(review_of(tool, by_url[golden_url]))
            n += 1
    _write(path, bench)
    cpath = lane / "results" / judge.model_dir / "candidates.json"
    cands = _read(cpath)
    stale: list[str] = []
    for golden_url, r in by_url.items():
        new = candidates_of(r)
        if (cands.get(golden_url) or {}).get(tool) not in (None, new):
            stale.append(golden_url)
        cands.setdefault(golden_url, {})[tool] = new
    _write(cpath, cands)
    # a review whose candidates changed is judged again: its dedup groups and evaluation row go
    for name in ("dedup_groups.json", "evaluations.json"):
        path = lane / "results" / judge.model_dir / name
        data = _read(path)
        if any(tool in (data.get(u) or {}) for u in stale):
            for u in stale:
                (data.get(u) or {}).pop(tool, None)
            _write(path, data)
    return n


def clear_tool(lane: Path, judge: Judge, tool: str) -> None:
    """Forgets a tool's judge files in a lane so it is judged afresh."""
    for name in JUDGE_FILES:
        path = lane / "results" / judge.model_dir / name
        data = _read(path)
        for golden_url in list(data):
            if isinstance(data[golden_url], dict):
                data[golden_url].pop(tool, None)
        _write(path, data)


def dedup_groups(lane: Path, judge: Judge, tool: str) -> dict[str, list]:
    return {url: rows[tool] for url, rows in _read(lane / "results" / judge.model_dir / "dedup_groups.json").items() if tool in rows}


def put_dedup_groups(lane: Path, judge: Judge, tool: str, groups: dict[str, list]) -> None:
    path = lane / "results" / judge.model_dir / "dedup_groups.json"
    data = _read(path)
    for url, g in groups.items():
        data.setdefault(url, {})[tool] = g
    _write(path, data)


def evaluations(lane: Path, judge: Judge) -> dict:
    return _read(lane / "results" / judge.model_dir / "evaluations.json")
