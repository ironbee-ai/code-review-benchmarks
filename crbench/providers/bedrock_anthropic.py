"""Claude on Bedrock through the Anthropic SDK: the Messages API at bedrock-runtime's /anthropic path with the
Bedrock bearer token. Effort goes as output_config.effort; thinking stays at the model's default (adaptive)."""
from __future__ import annotations

import time

import anthropic

from ..env import region, require
from .base import Completion, Provider, ProviderError, utc_now, with_retries


class BedrockAnthropic(Provider):
    route = "bedrock-anthropic"

    def __init__(self, timeout: float, attempts: int = 6):
        self.attempts = attempts
        self.deadline = timeout
        self.client = anthropic.AsyncAnthropic(
            base_url=f"https://bedrock-runtime.{region()}.amazonaws.com/anthropic",
            api_key=require("AWS_BEARER_TOKEN_BEDROCK"), timeout=timeout, max_retries=0)

    async def complete(self, system, user, params, max_output_tokens, model, provider_pin=None, temperature=None) -> Completion:
        kwargs: dict = {"model": model, "max_tokens": max_output_tokens, "system": system, "messages": [{"role": "user", "content": user}]}
        if params.get("effort"):
            kwargs["output_config"] = {"effort": params["effort"]}
        if temperature is not None:
            kwargs["temperature"] = temperature

        async def once():
            t0, started = time.time(), utc_now()
            first_chunk = first_text = None
            try:
                async with self.client.messages.stream(**kwargs) as s:
                    async for event in s:
                        if first_chunk is None:
                            first_chunk = int((time.time() - t0) * 1000)
                        if first_text is None and event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                            first_text = int((time.time() - t0) * 1000)
                    msg = await s.get_final_message()
            except anthropic.APIStatusError as e:
                raise ProviderError(f"HTTP {e.status_code}: {str(e)[:400]}", retryable=e.status_code in (408, 409, 429, 500, 502, 503, 504, 529), status=e.status_code) from e
            except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
                raise ProviderError(f"{type(e).__name__}: {str(e)[:300]}", retryable=True) from e
            text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
            u = msg.usage
            thinking = getattr(getattr(u, "output_tokens_details", None), "thinking_tokens", None)  # part of output_tokens
            usage = {"input": int(getattr(u, "input_tokens", 0) or 0), "output": int(getattr(u, "output_tokens", 0) or 0),
                     "reasoning": int(thinking) if isinstance(thinking, (int, float)) else None,
                     "cache_read": int(getattr(u, "cache_read_input_tokens", 0) or 0), "cache_write": int(getattr(u, "cache_creation_input_tokens", 0) or 0)}
            return Completion(text=text, usage=usage, served_model=getattr(msg, "model", None), finish_reason=getattr(msg, "stop_reason", None),
                              started_at=started, first_chunk_ms=first_chunk, first_text_ms=first_text, response_id=getattr(msg, "id", None),
                              latency_ms=int((time.time() - t0) * 1000),
                              raw={"id": getattr(msg, "id", None), "stop_reason": getattr(msg, "stop_reason", None), "usage": u.model_dump() if u else None})

        result, attempts = await with_retries(once, attempts=self.attempts, deadline=self.deadline)
        result.attempts = attempts
        return result
