"""Tests for the Ollama narrative client (respx-mocked, no network)."""
from __future__ import annotations

import httpx
import pytest
import respx
from tenacity import wait_none

from warn_v2.reports import ollama as ollama_mod
from warn_v2.reports.ollama import (
    DeadClient,
    OllamaClient,
    OllamaUnavailable,
    build_ollama_client,
    check_ollama_health,
)

BASE = "http://ollama.test:11434"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ollama_mod, "_RETRY_WAIT", wait_none())


@respx.mock
def test_narrate_returns_content_and_ignores_thinking():
    route = respx.post(f"{BASE}/api/chat").respond(
        json={"message": {"content": "Layoffs rose.", "thinking": "internal reasoning"}}
    )
    client = OllamaClient(base_url=BASE, model="gpt-oss:20b")
    out = client.narrate(system="sys", prompt="{}")
    assert out == "Layoffs rose."
    body = route.calls.last.request.content
    assert b'"stream": false' in body or b'"stream":false' in body
    assert b"gpt-oss:20b" in body
    # num_predict caps thinking + content combined on a reasoning model; 1200
    # and then 4000 were exhausted by chain-of-thought on the biggest payloads
    # (empty content after retries).
    assert b'"num_predict": 8000' in body or b'"num_predict":8000' in body


@respx.mock
def test_narrate_retries_5xx_then_succeeds():
    route = respx.post(f"{BASE}/api/chat")
    route.side_effect = [
        httpx.Response(500, text="boom"),
        httpx.Response(200, json={"message": {"content": "ok"}}),
    ]
    assert OllamaClient(base_url=BASE).narrate(system="s", prompt="p") == "ok"
    assert route.call_count == 2


@respx.mock
def test_narrate_empty_content_exhausts_retries():
    route = respx.post(f"{BASE}/api/chat").respond(json={"message": {"content": ""}})
    with pytest.raises(OllamaUnavailable, match="empty narrative"):
        OllamaClient(base_url=BASE).narrate(system="s", prompt="p")
    assert route.call_count == 3


@respx.mock
def test_narrate_connection_error():
    respx.post(f"{BASE}/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(OllamaUnavailable):
        OllamaClient(base_url=BASE).narrate(system="s", prompt="p")


@respx.mock
def test_narrate_4xx_fails_fast():
    route = respx.post(f"{BASE}/api/chat").respond(404, json={"error": "model not found"})
    with pytest.raises(OllamaUnavailable):
        OllamaClient(base_url=BASE).narrate(system="s", prompt="p")
    assert route.call_count == 1  # no retry on 4xx


@respx.mock
def test_check_ollama_health_true_on_success():
    respx.post(f"{BASE}/api/chat").respond(json={"message": {"content": "OK"}})
    assert check_ollama_health(OllamaClient(base_url=BASE)) is True


@respx.mock
def test_check_ollama_health_false_on_failure(caplog):
    respx.post(f"{BASE}/api/chat").respond(500, text="boom")
    assert check_ollama_health(OllamaClient(base_url=BASE)) is False
    assert "Ollama health check failed" in caplog.text


def test_check_ollama_health_reuses_narrate_retries():
    """No separate retry loop is layered on top -- narrate()'s own tenacity
    retryer (3 attempts) is what absorbs a transient blip."""
    calls = []

    class FlakyOnceClient:
        def narrate(self, *, system: str, prompt: str) -> str:
            calls.append(1)
            if len(calls) == 1:
                raise OllamaUnavailable("transient")
            return "OK"

    # A client that fails outright never recovers -- check_ollama_health
    # makes exactly one narrate() call and trusts its result.
    assert check_ollama_health(FlakyOnceClient()) is False
    assert calls == [1]


def test_dead_client_raises_immediately_no_state():
    client = DeadClient()
    with pytest.raises(OllamaUnavailable, match="health check"):
        client.narrate(system="sys", prompt="prompt")
    # Calling it again behaves identically -- no state, no network.
    with pytest.raises(OllamaUnavailable):
        client.narrate(system="sys", prompt="prompt")


def test_build_ollama_client_env_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://elsewhere:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:14b")
    client = build_ollama_client()
    assert client.model == "qwen3:14b"
    assert str(client._client.base_url) == "http://elsewhere:11434"

    monkeypatch.delenv("OLLAMA_BASE_URL")
    monkeypatch.delenv("OLLAMA_MODEL")
    client = build_ollama_client()
    assert client.model == "gpt-oss:20b"
    assert "ollama.ai.svc.cluster.local" in str(client._client.base_url)
