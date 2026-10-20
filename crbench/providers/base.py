from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field


@dataclass
class Completion:
    text: str
    usage: dict = field(default_factory=dict)      # input (uncached), output (incl. reasoning), reasoning, cache_read, cache_write
    cost_reported: float | None = None             # what the provider itself billed, when it says (OpenRouter)
    served_model: str | None = None
    provider_served: str | None = None             # OpenRouter's upstream provider name
    finish_reason: str | None = None
    latency_ms: int = 0
    attempts: int = 1
    raw: dict = field(default_factory=dict)
    started_at: str | None = None                  # UTC, when the successful attempt started
    first_chunk_ms: int | None = None              # first streamed event of any kind
    first_text_ms: int | None = None               # first token of the answer itself (after any reasoning)
    response_id: str | None = None                 # the provider's id (OpenRouter's generation id can be looked up later)
    failed_attempts: list = field(default_factory=list)   # [{at, seconds, error}] for the attempts before this one


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ProviderError(Exception):
    def __init__(self, message: str, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.failures: list[dict] = []           # every failed attempt, filled in by with_retries


class Provider:
    route: str = ""

    async def complete(self, system: str, user: str, params: dict, max_output_tokens: int, model: str,
                       provider_pin: dict | None = None, temperature: float | None = None) -> Completion:
        raise NotImplementedError


RETRY_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504, 529}


async def with_retries(call, attempts: int = 6, base: float = 2.0, cap: float = 90.0, deadline: float | None = None):
    """Runs `call()` again on a retryable ProviderError, with exponential backoff and jitter; returns the result and
    the number of attempts made. `deadline` bounds each attempt's wall-clock time: a stream kept open by keep-alive
    comments while nothing comes back would otherwise never time out. Every failed attempt is kept (when, how long,
    why) on the result's `failed_attempts`, or on the raised error's `failures`."""
    last: Exception | None = None
    timeouts = 0
    failures: list[dict] = []
    for i in range(attempts):
        at, t0 = utc_now(), time.time()
        try:
            result = await (asyncio.wait_for(call(), deadline) if deadline else call())
            if isinstance(result, Completion):
                result.failed_attempts = failures
            return result, i + 1
        except ProviderError as e:
            last = e
            failures.append({"at": at, "seconds": round(time.time() - t0, 1), "error": str(e)[:300]})
            if not e.retryable or i == attempts - 1:
                e.failures = failures
                raise
        except TimeoutError as e:
            last = e
            timeouts += 1
            failures.append({"at": at, "seconds": round(time.time() - t0, 1), "error": f"timeout after {deadline}s"})
            if timeouts >= 2 or i == attempts - 1:      # a call that ran out of time twice is not tried a third time
                err = ProviderError(f"timeout after {deadline}s (twice)" if deadline else f"timeout: {e}", retryable=False)
                err.failures = failures
                raise err from e
        await asyncio.sleep(min(cap, base * (2 ** i)) * (0.5 + random.random()))
    err = ProviderError(str(last) if last else "no answer", retryable=False)
    err.failures = failures
    raise err
