"""One client per route. A route is how a model is reached, never which model: bedrock-anthropic (the Messages API
on Bedrock's Anthropic endpoint, bearer token), bedrock-openai (Bedrock's OpenAI-compatible chat endpoint, the same
token), openrouter (OpenRouter's chat endpoint)."""
from __future__ import annotations

from .base import Completion, Provider, ProviderError


def make_provider(route: str, timeout: float, attempts: int = 6) -> Provider:
    if route == "bedrock-anthropic":
        from .bedrock_anthropic import BedrockAnthropic
        return BedrockAnthropic(timeout=timeout, attempts=attempts)
    if route in ("bedrock-openai", "openrouter"):
        from .openai_compat import OpenAICompat
        return OpenAICompat(route=route, timeout=timeout, attempts=attempts)
    raise ValueError(f"unknown route {route!r}")


__all__ = ["Completion", "Provider", "ProviderError", "make_provider"]
