"""One more call for runs whose reply is still not usable, up to the limit in configs/runs.yaml (parse_retries + 1
calls per run). Usage: python scripts/one_more_attempt.py <model>/<tier>/<pr>__r<n> ..."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crbench.cli import load_runs
from crbench.config import load_models
from crbench.env import load_env
from crbench.runner import RUNS, load_run, one_more_attempt, save_run


async def main(ids: list[str]) -> None:
    cfg = load_runs()
    models = {m.id: m for m in load_models()}

    async def one(run_id: str) -> None:
        path = RUNS / f"{run_id}.json"
        before = load_run(path)
        if len(before["calls"]) >= cfg.parse_retries + 1:
            print(f"{run_id}: already {len(before['calls'])} calls, the limit")
            return
        rec = await one_more_attempt(path, models[before["model_id"]], cfg)
        save_run(path, rec)
        print(f"{run_id}: {rec['status']}, {rec['finding_count']} findings, finish {rec['finish_reason']}, "
              f"calls {len(rec['calls'])}, last call {rec['calls'][-1]['usage']['output']} output tokens"
              + (", salvaged" if rec.get("salvaged") else ""))

    await asyncio.gather(*(one(i) for i in ids))


if __name__ == "__main__":
    load_env()
    asyncio.run(main(sys.argv[1:]))
