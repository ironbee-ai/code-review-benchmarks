"""The readiness check of a set (or some of its pull requests): for every configuration that is meant to run, is
there a current run (same prompt, parameters and provider pin) that answered in the JSON asked for, and a judged
record whose three voting judges and observers are the ones the pool gives today, each with a finished row for the
pull request, judging exactly the findings of that run? Prints one line per configuration and the problems found."""
from __future__ import annotations

from .config import JudgePool, Model, RunConfig, configs_for, judges_for, observers_for, tier_params, tool_name
from .dataset import load_pr, load_set
from .judge import load_judged
from .lane import candidates_of
from .prompt import build_prompt
from .runner import load_run, run_path


def check(models: list[Model], tiers: list[str], set_name: str, cfg: RunConfig, pool: JudgePool, repeats: list[int],
          prs: set[str] | None = None) -> list[dict]:
    entries = [e for e in load_set(cfg.sets[set_name]) if not prs or e["id"] in prs]
    system_text, user_t = cfg.prompt.system.read_text(), cfg.prompt.user.read_text()
    shas = {e["id"]: build_prompt(load_pr(e["id"]), cfg.prompt, system_text, user_t).sha for e in entries}
    rows = []
    for model, tier in configs_for(models, tiers, set_name):
        params, _ = tier_params(model, tier)
        want_judges = [j.id for j in judges_for(model.family, pool)]
        want_obs = [j.id for j in observers_for(model.family, pool)]
        for rep in repeats:
            problems: list[str] = []
            tool = tool_name(model.id, tier, rep)
            rec = load_judged(tool)
            served = set()
            findings = 0
            notes: list[str] = []
            for e in entries:
                run = load_run(run_path(model.id, tier, e["id"], rep))
                if run is None:
                    problems.append(f"{e['id']}: no run")
                    continue
                served.add(run.get("provider_served") or run.get("served_model") or "?")
                findings += run.get("finding_count") or 0
                if run.get("salvaged"):
                    notes.append(f"{e['id']}: reply not the JSON asked for ({run.get('finish_reason')}); {run.get('finding_count')} complete findings salvaged")
                if run.get("status") == "parse_error":   # a reply that is not the JSON asked for: judged as a review with no findings
                    notes.append(f"{e['id']}: reply not parseable ({run.get('finish_reason')}), judged as no findings")
                elif run.get("status") != "ok":
                    problems.append(f"{e['id']}: run status {run.get('status')} ({(run.get('error') or run.get('finish_reason') or '')[:80]})")
                if (run.get("prompt") or {}).get("sha") != shas[e["id"]]:
                    problems.append(f"{e['id']}: run made with another prompt")
                if run.get("params") != params:
                    problems.append(f"{e['id']}: run made with other parameters {run.get('params')}")
                if run.get("provider_pin") != model.provider:
                    problems.append(f"{e['id']}: run made with another provider pin {run.get('provider_pin')}")
                if rec is None:
                    continue
                url = e["golden_url"]
                voted = rec["voted"].get(url)
                if voted is None:
                    problems.append(f"{e['id']}: not voted")
                elif voted.get("incomplete"):
                    problems.append(f"{e['id']}: vote incomplete, missing {voted.get('missing_judges')}")
                want_texts = sorted(c["text"] for c in candidates_of(run))
                for jid, rows_by_url in list(rec["per_judge"].items()) + list((rec.get("per_observer") or {}).items()):
                    row = rows_by_url.get(url)
                    if row is None:
                        problems.append(f"{e['id']}: no row from {jid}")
                        continue
                    if row.get("errors_count", 0):
                        problems.append(f"{e['id']}: {jid} finished with {row['errors_count']} errors")
                    judged = sorted({x.get("matched_candidate") for x in row.get("true_positives", []) if x.get("matched_candidate")} |
                                    {(x["candidate"] if isinstance(x, dict) else x) for x in row.get("false_positives", [])})
                    if row.get("total_candidates") != len(want_texts) or not set(judged) <= set(want_texts):
                        problems.append(f"{e['id']}: {jid} judged other candidates than the run's findings")
            if rec is None:
                problems.append("not judged")
            else:
                if [j["id"] for j in rec["judges"]] != want_judges:
                    problems.append(f"judged by {[j['id'] for j in rec['judges']]}, the pool gives {want_judges}")
                if [j["id"] for j in rec.get("observers") or []] != want_obs:
                    problems.append(f"observers {[j['id'] for j in rec.get('observers') or []]}, the pool gives {want_obs}")
            rows.append({"config": f"{model.id}/{tier}/r{rep}", "route": model.route, "served": sorted(served), "findings": findings,
                         "judges": want_judges, "observers": want_obs, "problems": problems, "notes": notes})
    return rows
