"""The data: Martian's benchmark checkout at a pinned commit (work/martian), the PR index and the sets (data/sets),
the goldens and PR labels copied beside them (data/martian), and one snapshot per pull request fetched from the
benchmark's fork of it on GitHub (data/prs/<id>.json: title, description, shas, every changed file's patch and its
full content at the head)."""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import statistics
import subprocess
import time
from pathlib import Path

import httpx

from .env import ROOT

MARTIAN_REPO = "https://github.com/withmartian/code-review-benchmark"
MARTIAN_COMMIT = "e616e849755441da38f18bf3adba2c9583b03803"
WORK = ROOT / "work"
DATA = ROOT / "data"
PRS = DATA / "prs"
SETS = DATA / "sets"
MARTIAN_COPY = DATA / "martian"
FORK_TOOL_ORDER = ("claude", "augment", "coderabbit", "copilot", "claude-code", "bugbot", "baz")
CONTENT_MAX_BYTES = 1_000_000          # GitHub's contents API ceiling; a larger file is patch-only
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip",
              ".gz", ".jar", ".class", ".so", ".dylib", ".dll", ".exe", ".bin", ".lock", ".snap", ".mp4", ".webm", ".mp3"}
LANG_BY_EXT = {".py": "Python", ".go": "Go", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript",
               ".rb": "Ruby", ".erb": "Ruby", ".java": "Java", ".kt": "Kotlin", ".sql": "SQL", ".yaml": "YAML", ".yml": "YAML",
               ".json": "JSON", ".md": "Markdown", ".css": "CSS", ".scss": "SCSS", ".html": "HTML", ".hbs": "Handlebars",
               ".properties": "Properties", ".xml": "XML", ".sh": "Shell", ".toml": "TOML"}


def martian_offline() -> Path:
    return WORK / "martian" / "offline"


def fetch_martian(force: bool = False) -> Path:
    """Clones the benchmark at the pinned commit into work/martian (a plain checkout; nothing in it is executed from
    there except the benchmark's own steps, by the judge driver)."""
    dest = WORK / "martian"
    if dest.exists() and not force:
        head = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
        if head == MARTIAN_COMMIT:
            return martian_offline()
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", MARTIAN_REPO, str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "-q", MARTIAN_COMMIT], check=True)
    return martian_offline()


def pr_id_of(url: str) -> str:
    m = re.search(r"github\.com/[^/]+/([^/]+)/pull/(\d+)", url)
    if not m:
        raise ValueError(f"not a pull request url: {url}")
    return f"{m.group(1)}__{m.group(2)}"


def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if not m:
        raise ValueError(f"not a pull request url: {url}")
    return m.group(1), m.group(2), int(m.group(3))


def build_index() -> list[dict]:
    """data/sets/full.json from the checkout: one entry per benchmark PR with its golden url, the fork PR to fetch,
    the repo and the labels' language. Copies the goldens and labels into data/martian."""
    offline = martian_offline()
    with open(offline / "results" / "benchmark_data.json") as f:
        bench = json.load(f)
    with open(offline / "results" / "pr_labels.json") as f:
        labels = json.load(f)
    MARTIAN_COPY.mkdir(parents=True, exist_ok=True)
    (MARTIAN_COPY / "golden_comments").mkdir(exist_ok=True)
    for g in (offline / "golden_comments").glob("*.json"):
        shutil.copy(g, MARTIAN_COPY / "golden_comments" / g.name)
    shutil.copy(offline / "results" / "pr_labels.json", MARTIAN_COPY / "pr_labels.json")
    (MARTIAN_COPY / "COMMIT").write_text(MARTIAN_COMMIT + "\n")
    index: list[dict] = []
    for golden_url, entry in bench.items():
        reviews = {r["tool"]: r for r in entry.get("reviews", [])}
        fork = next((reviews[t]["pr_url"] for t in FORK_TOOL_ORDER if t in reviews), None)
        if fork is None and reviews:
            fork = next(iter(reviews.values()))["pr_url"]
        lab = labels.get(golden_url, {})
        index.append({
            "id": pr_id_of(golden_url),
            "golden_url": golden_url,
            "fork_pr_url": fork,
            "source_repo": entry.get("source_repo"),
            "title": entry.get("pr_title"),
            "language": (lab.get("derived") or {}).get("language"),
            "golden_count": len(entry.get("golden_comments", [])),
            "pr_size_category": (lab.get("llm_pr_labels") or {}).get("pr_size_category"),
            "benchmark_note": entry.get("az_comment"),   # the benchmark's own flag, e.g. "reviewed commit is not in the repo"
        })
    index.sort(key=lambda e: e["id"])
    SETS.mkdir(parents=True, exist_ok=True)
    with open(SETS / "full.json", "w") as f:
        json.dump(index, f, indent=1)
    return index


def load_set(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def load_pr(pr_id: str) -> dict:
    with open(PRS / f"{pr_id}.json") as f:
        return json.load(f)


class GitHub:
    def __init__(self, token: str):
        self.client = httpx.Client(base_url="https://api.github.com", timeout=60,
                                   headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "crbench"})

    def get(self, path: str, **params) -> httpx.Response:
        for attempt in range(6):
            r = self.client.get(path, params=params)
            if r.status_code in (403, 429) and "rate limit" in r.text.lower():
                reset = int(r.headers.get("x-ratelimit-reset", "0") or 0)
                time.sleep(max(5, min(900, reset - int(time.time()) + 2)))
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            return r
        return r

    def json(self, path: str, **params):
        r = self.get(path, **params)
        r.raise_for_status()
        return r.json()

    def paged(self, path: str, **params) -> list:
        out: list = []
        page = 1
        while True:
            chunk = self.json(path, per_page=100, page=page, **params)
            out.extend(chunk)
            if len(chunk) < 100:
                return out
            page += 1


def github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    raise SystemExit("no GITHUB_TOKEN and `gh auth token` gave nothing")


def _is_text_path(path: str) -> bool:
    return Path(path).suffix.lower() not in BINARY_EXT


def fetch_pr(gh: GitHub, entry: dict) -> dict:
    owner, repo, number = parse_pr_url(entry["fork_pr_url"])
    pr = gh.json(f"/repos/{owner}/{repo}/pulls/{number}")
    files = gh.paged(f"/repos/{owner}/{repo}/pulls/{number}/files")
    head = pr["head"]["sha"]
    out_files: list[dict] = []
    for f in files:
        rec = {"path": f["filename"], "status": f["status"], "additions": f.get("additions", 0), "deletions": f.get("deletions", 0),
               "patch": f.get("patch"), "content": None, "content_reason": None, "previous_path": f.get("previous_filename"),
               "language": LANG_BY_EXT.get(Path(f["filename"]).suffix.lower())}
        if f["status"] == "removed":
            rec["content_reason"] = "removed"
        elif not _is_text_path(f["filename"]) or (f.get("patch") is None and f.get("changes", 0) > 0 and f.get("additions", 0) == 0):
            rec["content_reason"] = "binary"
        else:
            r = gh.get(f"/repos/{owner}/{repo}/contents/{f['filename']}", ref=head)
            if r.status_code == 200 and r.json().get("encoding") == "base64":
                raw = base64.b64decode(r.json().get("content", ""))
                try:
                    rec["content"] = raw.decode("utf-8")
                except UnicodeDecodeError:
                    rec["content_reason"] = "not-utf8"
            elif r.status_code == 200 and r.json().get("size", 0) > CONTENT_MAX_BYTES:
                rec["content_reason"] = "too-large"
            else:
                rec["content_reason"] = f"http-{r.status_code}"
        out_files.append(rec)
    return {
        "id": entry["id"], "golden_url": entry["golden_url"], "fork_pr_url": entry["fork_pr_url"],
        "source_repo": entry.get("source_repo"), "language": entry.get("language"),
        "title": pr.get("title") or entry.get("title"), "description": pr.get("body") or "",
        "base_sha": pr["base"]["sha"], "head_sha": head, "changed_files": pr.get("changed_files"),
        "additions": pr.get("additions"), "deletions": pr.get("deletions"), "files": out_files,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def build_prs(index: list[dict], force: bool = False, log=print) -> list[str]:
    gh = GitHub(github_token())
    PRS.mkdir(parents=True, exist_ok=True)
    done: list[str] = []
    for entry in index:
        dest = PRS / f"{entry['id']}.json"
        if dest.exists() and not force:
            done.append(entry["id"])
            continue
        if not entry.get("fork_pr_url"):
            log(f"{entry['id']}: no fork PR url, skipped")
            continue
        snap = fetch_pr(gh, entry)
        with open(dest, "w") as f:
            json.dump(snap, f, indent=1)
        full = sum(1 for x in snap["files"] if x["content"] is not None)
        log(f"{entry['id']}: {len(snap['files'])} files, {full} with content, +{snap['additions']}/-{snap['deletions']}")
        done.append(entry["id"])
    return done


def make_subset(index: list[dict], per_repo: int = 2, seed: int = 20261016) -> list[dict]:
    """A stratified subset: per source repository (the five, forks folded into their repo), `per_repo` PRs chosen
    deterministically: the PR whose golden count is nearest the repository's median, then the one farthest from the
    first by size category, so each repository shows two sizes. Pull requests the benchmark itself flags (a reviewed
    commit missing from the repository, a PR assembled from several) are never chosen. Written to data/sets/frontier.json."""
    import random
    rnd = random.Random(seed)
    by_repo: dict[str, list[dict]] = {}
    for e in index:
        if e.get("benchmark_note"):
            continue
        key = (e.get("source_repo") or e["id"].split("__")[0]).replace("-greptile", "").replace("-graphite", "")
        by_repo.setdefault(key, []).append(e)
    chosen: list[dict] = []
    for repo in sorted(by_repo):
        entries = sorted(by_repo[repo], key=lambda e: e["id"])
        median = statistics.median([e["golden_count"] for e in entries])
        first = min(entries, key=lambda e: (abs(e["golden_count"] - median), rnd.random()))
        rest = [e for e in entries if e is not first]
        second = max(rest, key=lambda e: (e.get("pr_size_category") != first.get("pr_size_category"), abs(e["golden_count"] - median), rnd.random())) if rest else None
        chosen.extend([x for x in (first, second) if x][:per_repo])
    chosen.sort(key=lambda e: e["id"])
    with open(SETS / "frontier.json", "w") as f:
        json.dump(chosen, f, indent=1)
    return chosen
