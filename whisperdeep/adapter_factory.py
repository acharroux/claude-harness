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


def make_adapter(
    name: str,
    *,
    seed: Optional[int] = None,
    model: Optional[str] = None,
) -> LLMAdapter:
    """Construct an adapter by short name.

    Parameters
    ----------
    name
        One of ``offline`` / ``null`` / ``anthropic`` / ``openai``.
    seed
        Forwarded to the offline adapter for deterministic prose.
    model
        Optional model name. When provided and ``name`` is ``anthropic``
        or ``openai``, it is forwarded to the adapter's constructor.
        Ignored for ``offline`` and ``null`` adapters (those backends do
        not consume a model name). When omitted, each adapter falls back
        to its own built-in default.
    """
    key = (name or "").strip().lower()
    if key == "offline":
        return OfflineAdapter(seed=seed)
    if key == "null":
        return NullAdapter()
    if key == "anthropic":
        return AnthropicAdapter(model=model) if model is not None else AnthropicAdapter()
    if key == "openai":
        return OpenAIAdapter(model=model) if model is not None else OpenAIAdapter()
    raise ValueError(
        f"Unknown adapter {name!r}; choose one of {SUPPORTED}"
    )


__all__ = ["make_adapter", "SUPPORTED"]
