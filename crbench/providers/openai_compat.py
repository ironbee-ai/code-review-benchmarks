"""The chat-completions shape, twice: Bedrock's OpenAI-compatible endpoint (GPT, GLM, Kimi, Grok on Bedrock; bearer
token) and OpenRouter (everything else; its own key). Effort goes as `reasoning_effort` on Bedrock and as the
`reasoning` object on OpenRouter; OpenRouter also takes the provider pin and returns the cost it billed. Every call
streams so the final chunk carries the usage."""
from __future__ import annotations

import time

import openai

from ..env import region, require
from .base import Completion, Provider, ProviderError, utc_now, with_retries

OPENROUTER_URL = "https://openrouter.ai/api/v1"


def read_usage(u: dict | None) -> dict:
    """Our usage record from a chat-completions usage. `prompt_tokens` counts every input token, the ones read from and
    written to a cache included (Bedrock's GPT models: a 25,270-token prompt shows as 25,270 with 25,268 cache-write
    tokens, and as 2 plus 25,268 cached on a repeat), so `input` is what is left after both."""
    u = u or {}
    prompt = int(u.get("prompt_tokens") or 0)
    cached = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
    reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    cache_write = int(((u.get("prompt_tokens_details") or {}).get("cache_write_tokens")) or 0)
    return {"input": max(0, prompt - cached - cache_write), "output": int(u.get("completion_tokens") or 0),
            "reasoning": int(reasoning) if isinstance(reasoning, (int, float)) else None, "cache_read": cached, "cache_write": cache_write}


class OpenAICompat(Provider):
    def __init__(self, route: str, timeout: float, attempts: int = 6):
        self.route = route
        self.attempts = attempts
        self.deadline = timeout
        if route == "bedrock-openai":
            base_url, key, headers = f"https://bedrock-runtime.{region()}.amazonaws.com/openai/v1", require("AWS_BEARER_TOKEN_BEDROCK"), {}
        elif route == "openrouter":
            base_url, key, headers = OPENROUTER_URL, require("OPENROUTER_API_KEY"), {"HTTP-Referer": "https://github.com/ironbee-ai/code-review-benchmarks", "X-Title": "crbench"}
        else:
            raise ValueError(route)
        self.client = openai.AsyncOpenAI(base_url=base_url, api_key=key, timeout=timeout, max_retries=0, default_headers=headers)

    def body(self, system, user, params, max_output_tokens, model, provider_pin, temperature) -> dict:
        body: dict = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                      "stream": True, "stream_options": {"include_usage": True}}
        extra: dict = {}
        if self.route == "bedrock-openai":
            body["max_completion_tokens"] = max_output_tokens
            if params.get("reasoning_effort"):
                body["reasoning_effort"] = params["reasoning_effort"]
        else:
            body["max_tokens"] = max_output_tokens
            if params.get("reasoning"):
                extra["reasoning"] = dict(params["reasoning"])
            if provider_pin:
                extra["provider"] = dict(provider_pin)
        if temperature is not None:
            body["temperature"] = temperature
        if extra:
            body["extra_body"] = extra
        return body

    async def complete(self, system, user, params, max_output_tokens, model, provider_pin=None, temperature=None) -> Completion:
        body = self.body(system, user, params, max_output_tokens, model, provider_pin, temperature)

        async def once():
            t0, started = time.time(), utc_now()
            text: list[str] = []
            usage = None
            finish = None
            served = None
            provider = None
            rid = first_chunk = first_text = None
            try:
                stream = await self.client.chat.completions.create(**body)
                async for chunk in stream:
                    d = chunk.model_dump(exclude_none=True) if hasattr(chunk, "model_dump") else dict(chunk)
                    if d.get("error"):             # an error inside a 200 stream (OpenRouter: upstream rate limit, provider failure)
                        raise ProviderError(f"stream error: {str(d['error'])[:300]}", retryable=True)
                    if first_chunk is None:
                        first_chunk = int((time.time() - t0) * 1000)
                    rid = rid or d.get("id")
                    served = served or d.get("model")
                    provider = provider or d.get("provider")
                    if d.get("usage"):
                        usage = d["usage"]
                    for choice in d.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if isinstance(delta.get("content"), str):
                            if first_text is None and delta["content"]:
                                first_text = int((time.time() - t0) * 1000)
                            text.append(delta["content"])
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
            except openai.APIStatusError as e:
                raise ProviderError(f"HTTP {e.status_code}: {str(e)[:400]}", retryable=e.status_code in (408, 409, 425, 429, 500, 502, 503, 504, 529), status=e.status_code) from e
            except (openai.APIConnectionError, openai.APITimeoutError) as e:
                raise ProviderError(f"{type(e).__name__}: {str(e)[:300]}", retryable=True) from e
            except openai.APIError as e:                 # an error event in the stream
                raise ProviderError(f"{type(e).__name__}: {str(e)[:300]}", retryable=True) from e
            if not text and finish is None and usage is None:
                raise ProviderError("the stream ended with no reply, no finish reason and no usage", retryable=True)
            u = read_usage(usage)
            cost = (usage or {}).get("cost")
            return Completion(text="".join(text), usage=u, cost_reported=float(cost) if isinstance(cost, (int, float)) else None,
                              served_model=served, provider_served=provider, finish_reason=finish, started_at=started,
                              first_chunk_ms=first_chunk, first_text_ms=first_text, response_id=rid,
                              latency_ms=int((time.time() - t0) * 1000), raw={"usage": usage, "finish_reason": finish})

        result, attempts = await with_retries(once, attempts=self.attempts, deadline=self.deadline)
        result.attempts = attempts
        return result
