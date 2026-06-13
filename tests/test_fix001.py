"""Tests for fix-001: --whisperer-model CLI flag.

Covers FX1–FX5 from harness-state/sprints/fix-001/contract.json. None of
these tests make real network calls. The Anthropic/OpenAI adapter
constructors do not require API keys (the key is only checked at
``complete()`` call time), but we still scrub API keys from the test
environment for the CLI integration tests so we never accidentally dial
out.
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

from whisperdeep.adapter_factory import make_adapter
from whisperdeep.game import Game
from whisperdeep.llm import AnthropicAdapter, OfflineAdapter, OpenAIAdapter


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# FX1: make_adapter() threads ``model`` to the real-provider adapters.
# ---------------------------------------------------------------------------


def test_fx1_make_adapter_threads_model_to_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key-for-tests")
    a = make_adapter("anthropic", model="claude-haiku-4-5")
    assert isinstance(a, AnthropicAdapter)
    assert a.model == "claude-haiku-4-5"


def test_fx1_make_adapter_threads_model_to_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key-for-tests")
    a = make_adapter("openai", model="gpt-4o-mini-custom")
    assert isinstance(a, OpenAIAdapter)
    assert a.model == "gpt-4o-mini-custom"


def test_fx1_make_adapter_anthropic_default_when_no_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key-for-tests")
    a = make_adapter("anthropic")
    assert isinstance(a, AnthropicAdapter)
    # Adapter's own default kicks in; just confirm something was set.
    assert a.model is not None
    assert isinstance(a.model, str)
    assert a.model != ""


def test_fx1_make_adapter_openai_default_when_no_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key-for-tests")
    a = make_adapter("openai")
    assert isinstance(a, OpenAIAdapter)
    assert a.model is not None
    assert isinstance(a.model, str)
    assert a.model != ""


def test_fx1_make_adapter_offline_ignores_model():
    # The offline adapter must accept the call without complaint and
    # produce a usable adapter; ``model`` is silently ignored.
    a = make_adapter("offline", seed=1, model="claude-haiku-4-5")
    assert isinstance(a, OfflineAdapter)


# ---------------------------------------------------------------------------
# FX2: Game.from_seed() accepts ``model`` and forwards it.
# ---------------------------------------------------------------------------


def test_fx2_game_from_seed_signature_has_model_param():
    sig = inspect.signature(Game.from_seed)
    assert "model" in sig.parameters
    # Must be keyword-only so ordering of existing kwargs doesn't shift.
    p = sig.parameters["model"]
    assert p.kind in (
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    # Default is None per the contract (the CLI supplies the actual default).
    assert p.default is None


def test_fx2_game_from_seed_offline_with_model_constructs():
    g = Game.from_seed(
        seed=1, whisperer=True, adapter="offline", model="claude-haiku-4-5"
    )
    assert g.whisperer is not None


def test_fx2_game_from_seed_offline_without_model_still_works():
    g = Game.from_seed(seed=1, whisperer=True, adapter="offline")
    assert g.whisperer is not None


def test_fx2_game_from_seed_no_whisperer_with_model_constructs():
    # When whisperer is disabled the model param should still be tolerated.
    g = Game.from_seed(seed=1, whisperer=False, model="anything")
    assert g.whisperer is None


# ---------------------------------------------------------------------------
# FX3 / FX4 / FX5: CLI integration tests.
# ---------------------------------------------------------------------------


def _run_cli(*flags: str):
    cmd = [sys.executable, "-m", "whisperdeep", *flags]
    env = os.environ.copy()
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        env.pop(k, None)
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_fx3_help_documents_whisperer_model_flag():
    r = _run_cli("--help")
    assert r.returncode == 0, r.stderr
    # Argparse prints the option as ``--whisperer-model``; we just look
    # for the substring so word-wrapping doesn't break the assertion.
    assert "whisperer-model" in r.stdout
    assert "claude-haiku-4-5" in r.stdout


def test_fx4_headless_with_whisperer_model_succeeds():
    r = _run_cli(
        "--seed", "1",
        "--headless",
        "--whisperer", "offline",
        "--whisperer-model", "claude-haiku-4-5",
    )
    assert r.returncode == 0, r.stderr


def test_fx5_headless_without_whisperer_model_still_works():
    r = _run_cli("--seed", "1", "--headless")
    assert r.returncode == 0, r.stderr


def test_fx5_headless_no_whisperer_still_works():
    r = _run_cli("--seed", "1", "--headless", "--no-whisperer")
    assert r.returncode == 0, r.stderr
