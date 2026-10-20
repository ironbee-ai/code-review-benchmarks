import pytest

from crbench.config import Judge, JudgePool, Model, configs_for, judges_for, parse_tool_name, tier_params, tool_name
from crbench.metrics import cost_list, cost_uncached, fbeta, per_pr_counts, run_cost, score_counts, usage_summary
from crbench.providers.openai_compat import read_usage


def test_aliases_are_not_run_twice():
    m = Model(id="glm", family="zai", route="r", model="x", tiers={"low": {"e": "low"}, "default": {"e": "xhigh"}, "xhigh": {"same_as": "default"}}, sets=["full"])
    assert [t for _, t in configs_for([m], ["low", "default", "xhigh"], "full")] == ["low", "default"]
    assert tier_params(m, "xhigh") == ({"e": "xhigh"}, "default")
    assert configs_for([m], ["low"], "frontier") == []


def test_judges_skip_own_family():
    pool = JudgePool(pool=[Judge("g", "google", "r", "m"), Judge("x", "xai", "r", "m"), Judge("mi", "mistral", "r", "m"), Judge("k", "moonshot", "r", "m")])
    assert [j.id for j in judges_for("anthropic", pool)] == ["g", "x", "mi"]
    assert [j.id for j in judges_for("xai", pool)] == ["g", "mi", "k"]
    with pytest.raises(ValueError):
        judges_for("google", JudgePool(pool=pool.pool[:3]))


def test_tool_name_roundtrip():
    assert parse_tool_name(tool_name("claude-opus-5.5", "default", 2)) == ("claude-opus-5.5", "default", 2)


def test_fbeta_and_profile_counts():
    assert fbeta(0.5, 0.5, 1) == 0.5 and fbeta(0, 0, 2) == 0
    voted = {"u": {"true_positives": [{"golden_comment": "a", "category": "bug"}, {"golden_comment": "b", "category": "style"}],
                   "false_negatives": [{"golden_comment": "c", "category": "perf"}], "fp": 2}}
    counts = per_pr_counts(voted, "core", {})
    assert counts["u"] == (1, 2, 1)          # the style match is matched-excluded under core
    s = score_counts(counts, 2.0)
    assert s["precision"] == pytest.approx(1 / 3) and s["recall"] == 0.5


def test_costs():
    price = {"input": 2.0, "output": 10.0, "cache_read": 0.1, "cache_write": None}
    u = {"input": 1_000_000, "output": 100_000, "cache_read": 1_000_000, "cache_write": 0}
    assert cost_list(u, price) == pytest.approx(2.0 + 1.0 + 0.1)
    assert cost_uncached(u, price) == pytest.approx(4.0 + 1.0)
    assert cost_list(u, {"input": None, "output": 1}) is None


def test_long_context_rates_apply_per_request():
    price = {"input": 0.1, "output": 0.5, "cache_read": 0.01, "cache_write": None,
             "long_context": {"over": 100_000, "input": 0.5, "output": 2.5, "cache_read": 0.05}}
    short = {"input": 100_000, "output": 1_000_000, "cache_read": 0, "cache_write": 0}
    long = {"input": 60_000, "output": 1_000_000, "cache_read": 50_000, "cache_write": 0}  # the prompt counts cache reads
    assert cost_list(short, price) == pytest.approx(0.01 + 0.5)
    assert cost_list(long, price) == pytest.approx(0.03 + 2.5 + 0.0025)
    assert cost_uncached(long, price) == pytest.approx(0.055 + 2.5)
    run = {"usage": {}, "calls": [{"usage": short}, {"usage": long}]}   # a parse retry: each request priced on its own
    assert run_cost(run, price) == pytest.approx(0.51 + 2.5325)


def test_read_usage_takes_cache_writes_out_of_input():
    # Bedrock's GPT models: prompt_tokens counts the tokens written to the cache too
    u = read_usage({"prompt_tokens": 25270, "completion_tokens": 346,
                    "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 25268},
                    "completion_tokens_details": {"reasoning_tokens": 72}})
    assert u == {"input": 2, "output": 346, "reasoning": 72, "cache_read": 0, "cache_write": 25268}
    u = read_usage({"prompt_tokens": 25270, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 25268}})
    assert (u["input"], u["cache_read"], u["cache_write"]) == (2, 25268, 0)


def test_latency_percentiles():
    runs = [{"status": "ok", "usage": {}, "calls": [], "latency_ms": ms} for ms in (99_000, 118_000)]
    u = usage_summary(runs, None)
    assert u["latency_median_s"] == 108.5 and u["latency_p90_s"] == pytest.approx(116.1)
    assert usage_summary(runs[:1], None)["latency_p90_s"] == 99.0


def test_failed_attempts_are_kept():
    import asyncio

    from crbench.providers.base import Completion, ProviderError, with_retries
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderError("HTTP 429: slow down", retryable=True, status=429)
        return Completion(text="ok")

    result, attempts = asyncio.run(with_retries(flaky, attempts=3, base=0.01))
    assert attempts == 2 and len(result.failed_attempts) == 1 and "429" in result.failed_attempts[0]["error"]

    async def broken():
        raise ProviderError("HTTP 400: bad", retryable=False, status=400)

    with pytest.raises(ProviderError) as e:
        asyncio.run(with_retries(broken, attempts=3, base=0.01))
    assert len(e.value.failures) == 1
