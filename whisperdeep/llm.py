"""LLM adapter abstraction for Whisperdeep (Sprint 7).

This module is the boundary between the Whisperer service and any concrete
text-generation backend. It contains:

* ``LLMAdapter``      -- abstract base class. All adapters expose a single
                         ``complete(prompt, *, max_tokens, event_type=None)``
                         method that returns an ``AdapterResult``.
* ``AdapterResult``   -- the (text, tokens, adapter_name) triple returned by
                         ``complete()``.
* ``LLMUnavailable``  -- exception raised by adapters that need an API key
                         (or other runtime resource) that is missing.
* ``NullAdapter``     -- always returns the empty string with zero tokens.
* ``OfflineAdapter``  -- deterministic fallback prose drawn from a JSON pool
                         shipped alongside this module. Selection is
                         seedable.
* ``AnthropicAdapter`` / ``OpenAIAdapter``
                      -- real-provider stubs. They read API keys from
                         environment variables and raise ``LLMUnavailable``
                         if the key (or, only at call time, the SDK) is
                         missing. They never make network calls in this
                         sprint's automated tests.

Layering invariant: this module imports nothing from ``whisperdeep.game``,
``whisperdeep.world``, ``whisperdeep.floor``, or ``whisperdeep.render``.
"""
from __future__ import annotations

import json
import os
import random as _random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Result + exceptions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterResult:
    """Return value of ``LLMAdapter.complete``.

    text         -- the generated prose (may be empty for ``NullAdapter``).
    tokens       -- token count actually consumed (estimated for offline).
    adapter_name -- identifier of the adapter that produced the result.
    fallback     -- True iff this result came from an internal fallback path
                    (currently only set by adapters that internally degrade;
                    most adapters leave this False and the Whisperer sets the
                    higher-level fallback flag itself).
    """

    text: str
    tokens: int
    adapter_name: str
    fallback: bool = False


class LLMUnavailable(RuntimeError):
    """Raised when an adapter cannot service a request.

    Examples: missing API key, missing SDK install, unrecoverable network
    error. The Whisperer catches this and degrades to its offline fallback.
    """


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class LLMAdapter(ABC):
    """Abstract base for all LLM adapters.

    Concrete adapters implement ``complete``. They MUST NOT make network
    calls at import time; any third-party SDK should be imported lazily
    inside ``complete`` so that import of this module never fails because of
    a missing optional dependency.
    """

    name: str = "abstract"

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 64,
        event_type: Optional[str] = None,
    ) -> AdapterResult:
        """Synchronous single-shot completion."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# NullAdapter
# ---------------------------------------------------------------------------


class NullAdapter(LLMAdapter):
    """An adapter that always returns the empty string with zero tokens.

    Useful as a sentinel "no whispers please" backend and as a baseline in
    tests.
    """

    name = "null"

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 64,
        event_type: Optional[str] = None,
    ) -> AdapterResult:
        return AdapterResult(text="", tokens=0, adapter_name=self.name, fallback=False)


# ---------------------------------------------------------------------------
# Offline prose pool + OfflineAdapter
# ---------------------------------------------------------------------------


# The pool ships as a sibling JSON file. It MUST contain >= 8 distinct
# entries per canonical event type.
_POOL_FILENAME = "prose_pool.json"
_POOL_PATH = Path(__file__).resolve().parent / _POOL_FILENAME


def _load_pool() -> Dict[str, List[str]]:
    """Load the fallback prose pool from the shipped JSON resource.

    Returns a mapping ``event_type -> [str, ...]``. Raises ``RuntimeError``
    if the file is missing or malformed; this is loud-on-purpose because the
    pool is required for ``OfflineAdapter`` to function.
    """
    if not _POOL_PATH.exists():
        raise RuntimeError(
            f"Whisperer prose pool not found at {_POOL_PATH}. "
            "This file ships with whisperdeep and must be present."
        )
    with _POOL_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RuntimeError(f"Prose pool root must be a dict, got {type(data).__name__}")
    cleaned: Dict[str, List[str]] = {}
    for k, v in data.items():
        if not isinstance(v, list) or not all(isinstance(s, str) and s for s in v):
            raise RuntimeError(f"Pool entry for {k!r} must be a list of non-empty strings")
        cleaned[k] = list(v)
    return cleaned


# Module-level cache. The pool is small and immutable; loading once is fine.
_POOL_CACHE: Optional[Dict[str, List[str]]] = None


def get_prose_pool() -> Dict[str, List[str]]:
    """Public accessor for the fallback prose pool. Caches on first call."""
    global _POOL_CACHE
    if _POOL_CACHE is None:
        _POOL_CACHE = _load_pool()
    return _POOL_CACHE


class OfflineAdapter(LLMAdapter):
    """Deterministic fallback adapter that draws prose from the shipped pool.

    The prose pool is keyed by event type. Callers pass the ``event_type``
    hint via ``complete()``; if the hint is recognized, a string is drawn
    from that key's list. If the hint is missing or unknown, a string is
    drawn from the union of all pools (still deterministic per seed).

    Determinism: two ``OfflineAdapter`` instances constructed with the same
    ``seed`` produce identical sequences for the same sequence of
    ``event_type`` calls. Each instance owns its own ``random.Random`` so
    multiple adapters in the same process don't fight over global state.
    """

    name = "offline"

    # Estimated token cost per offline whisper. The Whisperer uses this to
    # account against the budget, even though no real tokens are spent. The
    # value is intentionally small to make the budget-exhaustion test
    # well-conditioned.
    DEFAULT_TOKENS_PER_CALL = 8

    def __init__(
        self,
        seed: Optional[int] = None,
        *,
        tokens_per_call: Optional[int] = None,
        pool: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        self._rng = _random.Random(seed)
        self._tokens_per_call = (
            int(tokens_per_call) if tokens_per_call is not None
            else self.DEFAULT_TOKENS_PER_CALL
        )
        self._pool: Dict[str, List[str]] = pool if pool is not None else get_prose_pool()
        # Build a flat union for the no-hint case.
        flat: List[str] = []
        for entries in self._pool.values():
            flat.extend(entries)
        self._flat_pool: List[str] = flat

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 64,
        event_type: Optional[str] = None,
    ) -> AdapterResult:
        if event_type and event_type in self._pool and self._pool[event_type]:
            entries = self._pool[event_type]
        else:
            entries = self._flat_pool
        if not entries:
            text = ""
        else:
            text = entries[self._rng.randrange(len(entries))]
        # Cap tokens at max_tokens for hygiene; offline tokens are estimated.
        tokens = min(self._tokens_per_call, max_tokens) if max_tokens > 0 else self._tokens_per_call
        return AdapterResult(text=text, tokens=tokens, adapter_name=self.name, fallback=False)


# ---------------------------------------------------------------------------
# Real-provider stubs
# ---------------------------------------------------------------------------


class AnthropicAdapter(LLMAdapter):
    """Stub adapter for Anthropic Claude.

    Reads ``ANTHROPIC_API_KEY`` at call time. If the key is missing OR the
    ``anthropic`` SDK is not installed, ``complete()`` raises
    ``LLMUnavailable``. Importing this class never fails because of those
    missing pieces (soft import inside ``complete``).
    """

    name = "anthropic"
    env_var: str = "ANTHROPIC_API_KEY"

    def __init__(self, model: str = "claude-3-5-haiku-latest") -> None:
        self.model = model

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 64,
        event_type: Optional[str] = None,
    ) -> AdapterResult:
        api_key = os.environ.get(self.env_var)
        if not api_key:
            raise LLMUnavailable(
                f"AnthropicAdapter: missing API key; set {self.env_var}"
            )
        try:
            import anthropic  # type: ignore  # noqa: F401  -- soft import
        except ImportError as exc:
            raise LLMUnavailable(
                "AnthropicAdapter: 'anthropic' SDK is not installed"
            ) from exc
        # Sprint 7 explicitly does NOT make a real network call from
        # automated tests. The body below is a real-shape skeleton; in
        # practice tests never reach this point because they don't set an
        # API key. We still raise LLMUnavailable rather than dialing out, so
        # CI is safe even if a key sneaks in.
        raise LLMUnavailable(  # pragma: no cover -- guarded by tests
            "AnthropicAdapter: live calls disabled in Sprint 7; "
            "set up the real client in a later sprint."
        )


class OpenAIAdapter(LLMAdapter):
    """Stub adapter for OpenAI. Mirrors AnthropicAdapter's behavior."""

    name = "openai"
    env_var: str = "OPENAI_API_KEY"

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 64,
        event_type: Optional[str] = None,
    ) -> AdapterResult:
        api_key = os.environ.get(self.env_var)
        if not api_key:
            raise LLMUnavailable(
                f"OpenAIAdapter: missing API key; set {self.env_var}"
            )
        try:
            import openai  # type: ignore  # noqa: F401  -- soft import
        except ImportError as exc:
            raise LLMUnavailable(
                "OpenAIAdapter: 'openai' SDK is not installed"
            ) from exc
        raise LLMUnavailable(  # pragma: no cover -- guarded by tests
            "OpenAIAdapter: live calls disabled in Sprint 7; "
            "set up the real client in a later sprint."
        )


__all__ = [
    "AdapterResult",
    "LLMUnavailable",
    "LLMAdapter",
    "NullAdapter",
    "OfflineAdapter",
    "AnthropicAdapter",
    "OpenAIAdapter",
    "get_prose_pool",
]
