"""Adapter factory: turn a CLI flag into a concrete LLMAdapter.

Lives in its own module so that:
* The :mod:`whisperdeep.whisperer` module never imports concrete
  real-provider adapter classes.
* The :mod:`whisperdeep.game` module never imports concrete adapters either
  — it imports this factory lazily inside :meth:`Game.from_seed`.

Supported names: ``offline``, ``null``, ``anthropic``, ``openai``.
"""
from __future__ import annotations

from typing import Optional

from .llm import (
    AnthropicAdapter,
    LLMAdapter,
    NullAdapter,
    OfflineAdapter,
    OpenAIAdapter,
)


SUPPORTED = ("offline", "null", "anthropic", "openai")


def make_adapter(name: str, *, seed: Optional[int] = None) -> LLMAdapter:
    """Construct an adapter by short name.

    Parameters
    ----------
    name
        One of ``offline`` / ``null`` / ``anthropic`` / ``openai``.
    seed
        Forwarded to the offline adapter for deterministic prose.
    """
    key = (name or "").strip().lower()
    if key == "offline":
        return OfflineAdapter(seed=seed)
    if key == "null":
        return NullAdapter()
    if key == "anthropic":
        return AnthropicAdapter()
    if key == "openai":
        return OpenAIAdapter()
    raise ValueError(
        f"Unknown adapter {name!r}; choose one of {SUPPORTED}"
    )


__all__ = ["make_adapter", "SUPPORTED"]
