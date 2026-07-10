"""Tests for the Ollama narrative client (respx-mocked, no network)."""
from __future__ import annotations

import httpx
import pytest
import respx
from tenacity import wait_none

from warn_v2.reports import ollama as ollama_mod
from warn_v2.reports.ollama import OllamaClient, OllamaUnavailable, build_ollama_client

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
