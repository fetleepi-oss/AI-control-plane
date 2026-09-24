import os
import time

import litellm

from models.models import ModelEntry
from config import settings


class ProviderExecutionError(Exception):
    def __init__(self, message: str, attempted: list[str]):
        super().__init__(message)
        self.attempted = attempted


def _resolve_credentials(model: ModelEntry) -> dict:
    """Look up server-side credentials for a model's provider. Never sourced
    from the client request — this is the whole point of the gateway."""
    provider = model.provider
    kwargs = {}
    if provider.kind == "openrouter":
        key = os.environ.get(provider.credential_ref or "OPENROUTER_API_KEY", settings.openrouter_api_key)
        if not key:
            raise ProviderExecutionError(f"No credential configured for provider '{provider.name}'", [])
        kwargs["api_key"] = key
    elif provider.kind == "ollama":
        kwargs["api_base"] = provider.base_url or settings.ollama_base_url
    return kwargs


def execute_with_fallback(
    primary: ModelEntry,
    fallbacks: list[ModelEntry],
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 1024,
    stream: bool = False,
):
    """Try the primary model, then each fallback in order. Returns
    (response, model_used, fallback_used, attempted_names, latency_ms)."""
    chain = [primary] + fallbacks
    attempted = []

    for model in chain:
        attempted.append(model.friendly_name)
        try:
            kwargs = _resolve_credentials(model)
            start = time.perf_counter()
            response = litellm.completion(
                model=model.litellm_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                timeout=30,
                **kwargs,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            return response, model, (model.id != primary.id), attempted, latency_ms
        except Exception:
            # Swallow and try the next model in the fallback chain. The last
            # failure is what gets surfaced to the caller if everything fails.
            continue

    raise ProviderExecutionError(
        f"All {len(chain)} candidate model(s) failed: {', '.join(attempted)}",
        attempted,
    )
