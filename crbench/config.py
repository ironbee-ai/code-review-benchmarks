"""The YAML configs under configs/ as plain dataclasses, plus the two rules the configs imply: which (model, tier)
pairs a set runs (aliases are not run twice) and which judges a model's family gets."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .env import ROOT

CONFIGS = ROOT / "configs"
TIERS = ("low", "default", "xhigh")


@dataclass
class Model:
    id: str
    family: str
    route: str
    model: str
    tiers: dict[str, dict]
    sets: list[str]
    provider: dict | None = None


@dataclass
class Judge:
    id: str
    family: str
    route: str
    model: str
    params: dict = field(default_factory=dict)
    drop: list[str] = field(default_factory=list)

    @property
    def model_dir(self) -> str:
        """The benchmark's results directory name for MARTIAN_MODEL (its sanitize_model_name)."""
        return self.model.strip().replace("/", "_")


@dataclass
class JudgePool:
    pool: list[Judge]
    per_candidate: int = 3
    dedup_with: str = "first"
    observers: list[Judge] = field(default_factory=list)


@dataclass
class Prompting:
    system: Path
    user: Path
    file_chars_max: int = 60000
    files_chars_budget: int = 500000
    patch_chars_max: int = 40000


@dataclass
class RunConfig:
    mode: str
    sets: dict[str, Path]
    repeats: int
    prompt: Prompting
    max_output_tokens: int
    timeout_seconds: int
    parse_retries: int
    concurrency: dict[str, int] = field(default_factory=dict)


def _load(name: str) -> dict:
    with open(CONFIGS / name) as f:
        return yaml.safe_load(f) or {}


def load_models() -> list[Model]:
    raw = _load("models.yaml")
    out: list[Model] = []
    for m in raw.get("models", []):
        out.append(Model(id=m["id"], family=m["family"], route=m["route"], model=m["model"],
                         tiers={k: (v or {}) for k, v in (m.get("tiers") or {}).items()},
                         sets=list(m.get("sets") or ["full"]), provider=m.get("provider")))
    return out


def load_judges() -> JudgePool:
    raw = _load("judges.yaml")
    def judge(j: dict) -> Judge:
        return Judge(id=j["id"], family=j["family"], route=j["route"], model=j["model"], params=dict(j.get("params") or {}), drop=list(j.get("drop") or []))
    return JudgePool(pool=[judge(j) for j in raw.get("pool", [])], per_candidate=int(raw.get("per_candidate", 3)),
                     dedup_with=str(raw.get("dedup_with", "first")), observers=[judge(j) for j in raw.get("observers") or []])


def load_pricing() -> dict[str, dict]:
    return _load("pricing.yaml").get("models", {})


def load_runs() -> RunConfig:
    raw = _load("runs.yaml")
    p = raw.get("prompt") or {}
    return RunConfig(
        mode=raw.get("mode", "diff-only"),
        sets={k: ROOT / v for k, v in (raw.get("sets") or {}).items()},
        repeats=int(raw.get("repeats", 1)),
        prompt=Prompting(system=ROOT / p.get("system", "configs/prompts/review_system.md"),
                         user=ROOT / p.get("user", "configs/prompts/review_user.md"),
                         file_chars_max=int(p.get("file_chars_max", 60000)),
                         files_chars_budget=int(p.get("files_chars_budget", 500000)),
                         patch_chars_max=int(p.get("patch_chars_max", 40000))),
        max_output_tokens=int(raw.get("max_output_tokens", 65536)),
        timeout_seconds=int(raw.get("timeout_seconds", 1500)),
        parse_retries=int(raw.get("parse_retries", 1)),
        concurrency={k: int(v) for k, v in (raw.get("concurrency") or {}).items()},
    )


def tier_skip(model: Model, tier: str) -> str | None:
    """Why a tier is not run (`skip: <reason>` in models.yaml), or None."""
    return (model.tiers.get(tier) or {}).get("skip")


def tier_params(model: Model, tier: str) -> tuple[dict, str | None]:
    """The provider parameters a tier sends, and the tier it is an alias of (same_as) if any."""
    spec = dict(model.tiers.get(tier) or {})
    spec.pop("skip", None)
    alias = spec.pop("same_as", None)
    if alias:
        return dict(model.tiers.get(alias) or {}), alias
    return spec, None


def configs_for(models: list[Model], tiers: list[str], set_name: str, only: set[str] | None = None) -> list[tuple[Model, str]]:
    """The (model, tier) pairs a set runs: models that list the set, tiers that are not aliases of another tier."""
    out: list[tuple[Model, str]] = []
    for m in models:
        if set_name not in m.sets:
            continue
        if only and m.id not in only:
            continue
        for t in tiers:
            if t not in m.tiers or tier_skip(m, t):
                continue
            _, alias = tier_params(m, t)
            if alias:
                continue
            out.append((m, t))
    return out


def observers_for(family: str, pool: JudgePool) -> list[Judge]:
    """The observers that judge a contestant: every observer outside its family (they do not vote)."""
    return [j for j in pool.observers if j.family != family]


def judges_for(family: str, pool: JudgePool) -> list[Judge]:
    """The first `per_candidate` judges whose family is not the contestant's, in pool order."""
    picked = [j for j in pool.pool if j.family != family][: pool.per_candidate]
    if len(picked) < pool.per_candidate:
        raise ValueError(f"the judge pool has fewer than {pool.per_candidate} judges outside family {family!r}")
    return picked


def tool_name(model_id: str, tier: str, repeat: int) -> str:
    """The name a (model, tier, repeat) carries inside the benchmark (its `tool`)."""
    return f"{model_id}__{tier}__r{repeat}"


def parse_tool_name(name: str) -> tuple[str, str, int]:
    model_id, tier, rep = name.rsplit("__", 2)
    return model_id, tier, int(rep[1:])
