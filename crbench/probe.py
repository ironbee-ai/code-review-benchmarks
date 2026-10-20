"""One small call per (model, tier) and per judge before any real run: does the route take the parameters, does the
model answer in the JSON asked for, which usage fields come back (reasoning tokens, cache, the reported cost), what
model served it. Results go to results/probe.json; nothing here is scored."""
from __future__ import annotations

import asyncio
import json
import time

import httpx

from .config import JudgePool, Model, RunConfig, tier_params
from .env import ROOT
from .judge_proxy import JudgeProxy
from .prompt import parse_findings
from .providers import ProviderError, make_provider

PROBE_USER = """# Pull request: Fix pagination offset

Repository: demo (primary language: Python)

## Changed files (1)

### `app/pages.py` (modified, +3/-3)

Full content at the head (line numbers on the left):
```
1 | def page(items, number, size):
2 |     start = number * size + 1
3 |     end = start + size
4 |     return items[start:end]
```

Unified diff:
```diff
@@ -1,4 +1,4 @@
 def page(items, number, size):
-    start = number * size
+    start = number * size + 1
     end = start + size
     return items[start:end]
```
"""

JUDGE_PROBE = """You are evaluating AI code review tools.
Determine if the candidate issue matches the golden (expected) comment.

Golden Comment (the issue we're looking for):
The page start is off by one: `number * size + 1` skips the first item of every page.

Candidate Issue (from the tool's review):
pages.py line 2 adds 1 to the start index, so each page drops its first element.

Instructions:
- Determine if the candidate identifies the SAME underlying issue as the golden comment
- Accept semantic matches - different wording is fine if it's the same problem
- Focus on whether they point to the same bug, concern, or code issue

Respond with ONLY a JSON object:
{"reasoning": "brief explanation", "match": true/false, "confidence": 0.0-1.0}"""


async def probe_models(models: list[Model], tiers: list[str], cfg: RunConfig, max_output_tokens: int = 16000, timeout: float = 240,
                       on_row=None) -> list[dict]:
    system_text = cfg.prompt.system.read_text()
    providers = {}

    async def one(m: Model, tier: str) -> dict:
        params, alias = tier_params(m, tier)
        row = {"kind": "model", "id": m.id, "tier": tier, "route": m.route, "model": m.model, "params": params, "alias_of": alias}
        if alias:
            row["status"] = "alias"
            return row
        if m.route not in providers:
            providers[m.route] = make_provider(m.route, timeout, attempts=2)
        prov = providers[m.route]
        t0 = time.time()
        try:
            c = await asyncio.wait_for(prov.complete(system_text, PROBE_USER, params, max_output_tokens, m.model, provider_pin=m.provider), timeout * 2 + 30)
        except (ProviderError, TimeoutError) as e:
            row.update({"status": "error", "error": f"{type(e).__name__}: {str(e)[:600]}", "seconds": round(time.time() - t0, 1)})
            return row
        findings = parse_findings(c.text)
        row.update({"status": "ok" if findings is not None else "parse_error", "findings": len(findings or []), "usage": c.usage,
                    "cost_reported": c.cost_reported, "served_model": c.served_model, "provider_served": c.provider_served,
                    "finish_reason": c.finish_reason, "seconds": round(c.latency_ms / 1000, 1), "http_attempts": c.attempts,
                    "reply_head": c.text[:300]})
        return row

    out = []
    for fut in asyncio.as_completed([one(m, t) for m in models for t in tiers if t in m.tiers]):
        row = await fut
        out.append(row)
        if on_row:
            on_row(row)
    return out


def probe_judges(pool: JudgePool, on_row=None) -> list[dict]:
    judges = {j.id: j for j in pool.pool + pool.observers}
    out: list[dict] = []
    with JudgeProxy(judges) as proxy, httpx.Client(timeout=200) as client:
        for jid, j in judges.items():
            body = {"model": j.model, "temperature": 0.0, "messages": [
                {"role": "system", "content": "You are a precise code review evaluator. Always respond with valid JSON."},
                {"role": "user", "content": JUDGE_PROBE}]}
            t0 = time.time()
            r = client.post(proxy.base_url(jid, "probe", "-") + "/chat/completions", json=body, headers={"Authorization": "Bearer crbench-proxy"})
            row = {"kind": "judge", "id": jid, "route": j.route, "model": j.model, "params": j.params, "status_code": r.status_code, "seconds": round(time.time() - t0, 1)}
            if r.status_code == 200:
                data = r.json()
                content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                try:
                    verdict = json.loads(content.strip().strip("`").removeprefix("json").strip())
                except ValueError:
                    verdict = None
                row.update({"status": "ok" if isinstance(verdict, dict) and "match" in verdict else "parse_error", "verdict": verdict,
                            "usage": data.get("usage"), "reply_head": content[:200]})
            else:
                row.update({"status": "error", "error": r.text[:600]})
            out.append(row)
            if on_row:
                on_row(row)
    return out


def save(rows: list[dict]) -> str:
    path = ROOT / "results" / "probe.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = []
    if path.exists():
        with open(path) as f:
            old = json.load(f)
    key = lambda r: (r["kind"], r["id"], r.get("tier"))
    merged = {key(r): r for r in old}
    for r in rows:
        r["probed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        merged[key(r)] = r
    with open(path, "w") as f:
        json.dump(sorted(merged.values(), key=lambda r: (r["kind"], r["id"], r.get("tier") or "")), f, indent=1)
    return str(path)
