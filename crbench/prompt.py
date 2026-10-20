"""The one prompt every model gets, and the reading of its answer. The user part holds the pull request: title,
description, the changed-file table, and per file its full content at the head (numbered lines) and the unified diff.
A budget keeps the prompt bounded: files over `file_chars_max`, and the largest files once `files_chars_budget` is
exceeded, are shown as their patch only; a patch over `patch_chars_max` is cut with a marker."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from .config import Prompting

CATEGORIES = ("bug", "security", "concurrency", "data", "api", "perf", "test_gap", "doc_defect", "style", "speculative")
SEVERITIES = ("low", "medium", "high", "critical")


@dataclass
class Prompt:
    system: str
    user: str
    chars: int = 0
    sha: str = ""
    patch_only: list[str] = field(default_factory=list)
    cut_patches: list[str] = field(default_factory=list)


def numbered(content: str) -> str:
    lines = content.split("\n")
    width = len(str(len(lines)))
    return "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(lines, 1))


def build_prompt(pr: dict, prompting: Prompting, system_text: str, user_template: str) -> Prompt:
    files = pr.get("files") or []
    table = ["| file | status | +/- | shown as |", "|---|---|---|---|"]
    full_ok = [f for f in files if f.get("content") is not None and len(f["content"]) <= prompting.file_chars_max]
    full_ok.sort(key=lambda f: len(f["content"]))
    budget = prompting.files_chars_budget
    with_content: set[str] = set()
    for f in full_ok:
        if budget - len(f["content"]) < 0:
            continue
        budget -= len(f["content"])
        with_content.add(f["path"])
    patch_only = [f["path"] for f in files if f["path"] not in with_content]
    cut: list[str] = []
    sections: list[str] = []
    for f in files:
        shown = "full content + diff" if f["path"] in with_content else "diff only"
        table.append(f"| `{f['path']}` | {f['status']} | +{f.get('additions', 0)}/-{f.get('deletions', 0)} | {shown} |")
        parts = [f"### `{f['path']}` ({f['status']}, +{f.get('additions', 0)}/-{f.get('deletions', 0)})"]
        if f.get("previous_path"):
            parts.append(f"Renamed from `{f['previous_path']}`.")
        if f["path"] in with_content:
            parts.append("Full content at the head (line numbers on the left):")
            parts.append("```\n" + numbered(f["content"]) + "\n```")
        patch = f.get("patch")
        if patch:
            if len(patch) > prompting.patch_chars_max:
                patch = patch[: prompting.patch_chars_max] + "\n[... patch cut here: it exceeds the prompt's patch budget ...]"
                cut.append(f["path"])
            parts.append("Unified diff:")
            parts.append("```diff\n" + patch + "\n```")
        else:
            parts.append("(no textual diff: binary or too large)")
        sections.append("\n\n".join(parts))
    user = user_template.format(
        title=pr.get("title") or "", repo=pr.get("source_repo") or "", language=pr.get("language") or "unknown",
        base_sha=pr.get("base_sha") or "", head_sha=pr.get("head_sha") or "",
        description=(pr.get("description") or "").strip() or "(no description)",
        file_count=len(files), file_table="\n".join(table), files="\n\n".join(sections),
    )
    chars = len(system_text) + len(user)
    sha = hashlib.sha256((system_text + "\n\x00\n" + user).encode("utf-8")).hexdigest()[:16]
    return Prompt(system=system_text, user=user, chars=chars, sha=sha, patch_only=patch_only, cut_patches=cut)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _top_level_objects(text: str) -> list[dict]:
    """Every top-level JSON object in a text, in order (prose around them may hold braces of its own)."""
    dec, i, out = json.JSONDecoder(), 0, []
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
        i = end
    return out


def extract_json_object(text: str) -> dict | None:
    """The JSON object of a reply: the whole text, the text without code fences, the widest {...} span, or else the
    last top-level object in the text (a model that writes its reasoning before the JSON)."""
    if not text:
        return None
    candidates = [text.strip(), _FENCE.sub("", text).strip()]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start: end + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    objs = _top_level_objects(text)
    with_findings = [o for o in objs if "findings" in o]
    return (with_findings or objs or [None])[-1]


def parse_findings(text: str) -> list[dict] | None:
    """The findings of a reply as normalized records, or None when the reply is not the JSON asked for."""
    obj = extract_json_object(text)
    if obj is None:
        return None
    raw = obj.get("findings")
    if raw is None and isinstance(obj.get("issues"), list):
        raw = obj["issues"]
    if not isinstance(raw, list):
        return None
    return _normalize(raw)


def _normalize(raw: list) -> list[dict]:
    out: list[dict] = []
    for i, f in enumerate(raw):
        if not isinstance(f, dict):
            continue
        body = str(f.get("body") or f.get("description") or f.get("message") or "").strip()
        title = str(f.get("title") or "").strip()
        if not body and not title:
            continue
        line = f.get("line", f.get("line_start"))
        try:
            line = int(line) if line is not None else None
        except (TypeError, ValueError):
            line = None
        severity = str(f.get("severity") or "").strip().lower()
        category = str(f.get("category") or "").strip().lower()
        out.append({
            "index": i,
            "file": str(f.get("file") or f.get("path") or "").strip(),
            "line": line,
            "severity": severity if severity in SEVERITIES else (severity or None),
            "category": category if category in CATEGORIES else (category or None),
            "title": title,
            "body": body,
        })
    return out


def repair_escapes(text: str) -> str:
    r"""Drops the backslash of an escape JSON does not have (a model writing \` for a backtick); keeps valid ones."""
    return re.sub(r"\\(.)", lambda m: m.group(0) if m.group(1) in '"\\/bfnrtu' else m.group(1), text, flags=re.DOTALL)


def salvage_findings(text: str) -> list[dict] | None:
    """The findings of a reply that is not the JSON asked for: the reply with its invalid escapes repaired, or else
    every complete finding object in it (a reply cut at the output cap keeps the findings written before the cut; a
    finding whose own JSON is broken is lost). None when nothing can be read."""
    if not text:
        return None
    fixed = repair_escapes(text)
    found = parse_findings(fixed)
    if found is not None:
        return found
    dec, i, items = json.JSONDecoder(strict=False), 0, []
    while (i := fixed.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(fixed, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and isinstance(obj.get("findings"), list):
            items.extend(obj["findings"])
            i = end
        elif isinstance(obj, dict) and ("title" in obj or "body" in obj):
            items.append(obj)
            i = end
        else:
            i += 1
    out = _normalize(items)
    return out or None


def finding_text(finding: dict) -> str:
    """What the judge reads for a finding: the title and the body (the benchmark's candidate text)."""
    title, body = finding.get("title") or "", finding.get("body") or ""
    if title and body and not body.startswith(title):
        return f"{title}\n\n{body}"
    return body or title
