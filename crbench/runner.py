"""The review runs: every (model, tier, pull request, repeat) of a set is one call, saved as one JSON record under
results/runs/<model>/<tier>/<pr>__r<n>.json. A record that exists with status ok or parse_error is not run again
(force re-runs it); one that errored is. Calls run concurrently, bounded per route."""
from __future__ import annotations

import asyncio
import json
import time
import traceback
from pathlib import Path

from tqdm import tqdm

from .config import Model, RunConfig, configs_for, tier_params
from .dataset import load_pr, load_set
from .env import ROOT
from .prompt import build_prompt, parse_findings, salvage_findings
from .providers import ProviderError, make_provider

RUNS = ROOT / "results" / "runs"
CUT = ("length", "max_tokens")   # finish reasons of a reply cut at the output cap


def run_path(model_id: str, tier: str, pr_id: str, repeat: int) -> Path:
    return RUNS / model_id / tier / f"{pr_id}__r{repeat}.json"


def load_run(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def runs_of(model_id: str, tier: str) -> list[dict]:
    out = []
    for p in sorted((RUNS / model_id / tier).glob("*.json")) if (RUNS / model_id / tier).exists() else []:
        out.append(load_run(p))
    return out


def save_run(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(rec, f, indent=1)
    tmp.replace(path)


def _needs_run(path: Path, force: bool, prompt_sha: str, params: dict, provider_pin: dict | None) -> bool:
    """A run is made again when forced, when it has no reply, or when it was made with another prompt, other
    parameters or another provider pin."""
    if force:
        return True
    rec = load_run(path)
    if rec is None or rec.get("status") not in ("ok", "parse_error"):
        return True
    return ((rec.get("prompt") or {}).get("sha") != prompt_sha or rec.get("params") != params
            or rec.get("provider_pin") != provider_pin)


async def _one(provider, model: Model, tier: str, params: dict, pr: dict, repeat: int, cfg: RunConfig, system_text: str, user_template: str, set_name: str) -> dict:
    prompt = build_prompt(pr, cfg.prompt, system_text, user_template)
    record: dict = {
        "run_id": f"{model.id}__{tier}__{pr['id']}__r{repeat}", "model_id": model.id, "family": model.family, "route": model.route,
        "provider_model": model.model, "provider_pin": model.provider, "tier": tier, "params": params, "set": set_name, "pr_id": pr["id"], "golden_url": pr["golden_url"],
        "repeat": repeat, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "mode": cfg.mode,
        "prompt": {"chars": prompt.chars, "sha": prompt.sha, "patch_only": prompt.patch_only, "cut_patches": prompt.cut_patches,
                   "system_path": str(cfg.prompt.system.relative_to(ROOT)), "user_path": str(cfg.prompt.user.relative_to(ROOT))},
        "attempts": 0, "calls": [],
    }
    findings = None
    last = None
    for attempt in range(cfg.parse_retries + 1):
        try:
            c = await provider.complete(prompt.system, prompt.user, params, cfg.max_output_tokens, model.model, provider_pin=model.provider)
        except ProviderError as e:
            record.update({"status": "error", "error": str(e), "attempts": record["attempts"] + 1, "failed_attempts": getattr(e, "failures", [])})
            return record
        last = c
        record["attempts"] += c.attempts
        record["calls"].append(_call_record(c))
        findings = parse_findings(c.text)
        if findings is not None:
            break
    return _finish(record, findings, last)


def _call_record(c) -> dict:
    return {"usage": c.usage, "cost_reported": c.cost_reported, "latency_ms": c.latency_ms, "finish_reason": c.finish_reason,
            "served_model": c.served_model, "provider_served": c.provider_served, "http_attempts": c.attempts, "text_chars": len(c.text),
            "raw_usage": c.raw.get("usage"),  # the provider's own usage object, for audits
            "started_at": c.started_at, "first_chunk_ms": c.first_chunk_ms, "first_text_ms": c.first_text_ms,
            "response_id": c.response_id, "failed_attempts": c.failed_attempts}


def _finish(record: dict, findings: list | None, last) -> dict:
    """A run's outcome from its calls. Still not the JSON after the last attempt: a reply that finished keeps every
    complete finding it wrote; a reply cut at the output cap is an unfinished review and stays empty."""
    if findings is None and last is not None and last.finish_reason not in CUT:
        findings = salvage_findings(last.text)
        if findings is not None:
            record["salvaged"] = True
    calls = record["calls"]
    usage = {k: sum((x["usage"].get(k) or 0) for x in calls) for k in ("input", "output", "cache_read", "cache_write")}
    reasoning = [x["usage"].get("reasoning") for x in calls]
    usage["reasoning"] = sum(r for r in reasoning if r is not None) if any(r is not None for r in reasoning) else None
    costs = [x["cost_reported"] for x in calls if x["cost_reported"] is not None]
    record.update({
        "status": "ok" if findings is not None else "parse_error",
        "usage": usage, "cost_reported": sum(costs) if costs else None, "latency_ms": sum(x["latency_ms"] for x in calls),
        "served_model": last.served_model if last else None, "provider_served": last.provider_served if last else None,
        "finish_reason": last.finish_reason if last else None, "response_text": last.text if last else "",
        "findings": findings or [], "finding_count": len(findings or []),
    })
    return record


async def one_more_attempt(path: Path, model: Model, cfg: RunConfig) -> dict:
    """One more call for a run whose reply is still not usable (a run gets at most parse_retries + 1 calls; this is
    how a run made under a smaller limit gets the calls a larger one allows). The call is added to the run's calls."""
    rec = load_run(path)
    params, _ = tier_params(model, rec["tier"])
    prompt = build_prompt(load_pr(rec["pr_id"]), cfg.prompt, cfg.prompt.system.read_text(), cfg.prompt.user.read_text())
    if prompt.sha != rec["prompt"]["sha"] or params != rec["params"]:
        raise ValueError(f"{path}: made with another prompt or parameters; run it again instead")
    provider = make_provider(model.route, cfg.timeout_seconds)
    try:
        c = await provider.complete(prompt.system, prompt.user, params, cfg.max_output_tokens, model.model, provider_pin=model.provider)
    except ProviderError as e:
        rec.setdefault("failed_attempts", []).extend(getattr(e, "failures", []))
        return rec
    rec["attempts"] += c.attempts
    rec["calls"].append(_call_record(c))
    rec["attempt_note"] = f"{time.strftime('%Y-%m-%d')}: call {len(rec['calls'])} added (at most {cfg.parse_retries + 1} calls per run)"
    return _finish(rec, parse_findings(c.text), c)


async def run_matrix(models: list[Model], tiers: list[str], set_name: str, cfg: RunConfig, repeats: list[int], only: set[str] | None = None,
                     limit: int | None = None, force: bool = False, dry_run: bool = False, prs: set[str] | None = None, log=print) -> dict:
    entries = load_set(cfg.sets[set_name])
    if prs:
        entries = [e for e in entries if e["id"] in prs]
    if limit:
        entries = entries[:limit]
    system_text = cfg.prompt.system.read_text()
    user_template = cfg.prompt.user.read_text()
    shas = {e["id"]: build_prompt(load_pr(e["id"]), cfg.prompt, system_text, user_template).sha for e in entries}
    configs = configs_for(models, tiers, set_name, only)
    jobs: list[tuple[Model, str, dict, dict, int]] = []
    skipped = 0
    for model, tier in configs:
        params, _ = tier_params(model, tier)
        for e in entries:
            for rep in repeats:
                path = run_path(model.id, tier, e["id"], rep)
                if not _needs_run(path, force, shas[e["id"]], params, model.provider):
                    skipped += 1
                    continue
                jobs.append((model, tier, params, e, rep))
    log(f"{len(configs)} configs x {len(entries)} PRs x {len(repeats)} repeats: {len(jobs)} to run, {skipped} already done")
    if dry_run or not jobs:
        return {"to_run": len(jobs), "skipped": skipped, "ok": 0, "errors": 0, "parse_errors": 0}
    providers: dict[str, object] = {}
    sems: dict[str, asyncio.Semaphore] = {}
    model_sems: dict[str, asyncio.Semaphore] = {}
    for model, _ in configs:
        if model.route not in providers:
            providers[model.route] = make_provider(model.route, cfg.timeout_seconds)
            sems[model.route] = asyncio.Semaphore(cfg.concurrency.get(model.route, 8))
        model_sems.setdefault(model.id, asyncio.Semaphore(cfg.concurrency.get("per_model", 4)))
    counts = {"ok": 0, "errors": 0, "parse_errors": 0}
    bar = tqdm(total=len(jobs), unit="run")

    async def work(model: Model, tier: str, params: dict, e: dict, rep: int):
        async with model_sems[model.id], sems[model.route]:
            try:
                pr = load_pr(e["id"])
                rec = await _one(providers[model.route], model, tier, params, pr, rep, cfg, system_text, user_template, set_name)
            except Exception as ex:  # noqa: BLE001  a bug in the harness is recorded on the run, never lost
                rec = {"run_id": f"{model.id}__{tier}__{e['id']}__r{rep}", "model_id": model.id, "tier": tier, "pr_id": e["id"], "repeat": rep,
                       "set": set_name, "status": "error", "error": f"harness: {type(ex).__name__}: {ex}", "traceback": traceback.format_exc()[-2000:]}
            await asyncio.to_thread(save_run, run_path(model.id, tier, e["id"], rep), rec)
            key = {"ok": "ok", "parse_error": "parse_errors"}.get(rec["status"], "errors")
            counts[key] += 1
            bar.set_postfix(**counts)
            bar.update(1)

    await asyncio.gather(*(work(*j) for j in jobs))
    bar.close()
    return {"to_run": len(jobs), "skipped": skipped, **counts}
