"""Ollama narrative client for the sentiment reports.

The report job runs in the warn-v2 namespace with no GPU of its own —
inference happens on the cluster's shared Ollama service (GPU node). The
`NarrativeClient` Protocol mirrors warn_v2.enrichment.agent's LLMClient so
tests inject a fake and never touch the network.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://ollama.ai.svc.cluster.local:11434"
DEFAULT_MODEL = "gpt-oss:20b"

# Module-level so tests can swap in tenacity.wait_none() and skip real backoff.
_RETRY_WAIT = wait_exponential(multiplier=4, max=30)


class OllamaUnavailable(RuntimeError):
    """Ollama could not produce a narrative (after retries where sensible)."""


class _RetryableError(RuntimeError):
    """Transient failure: transport error, 5xx, or empty/bad payload."""


class NarrativeClient(Protocol):
    """Minimal narrative interface; tests inject fakes."""

    def narrate(self, *, system: str, prompt: str) -> str: ...


class OllamaClient:
    """Blocking client for Ollama's /api/chat endpoint."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        *,
        timeout_s: float = 300.0,
    ) -> None:
        self.model = model
        # Long read timeout: the first call after a quiet week may cold-load
        # the 20b model's weights onto the GPU before generating a token.
        self._client = httpx.Client(
            base_url=base_url, timeout=httpx.Timeout(10.0, read=timeout_s)
        )

    def narrate(self, *, system: str, prompt: str) -> str:
        retryer = Retrying(
            stop=stop_after_attempt(3),
            wait=_RETRY_WAIT,
            retry=retry_if_exception_type(_RetryableError),
            reraise=True,
        )
        try:
            return retryer(self._narrate_once, system, prompt)
        except _RetryableError as exc:
            raise OllamaUnavailable(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            # 4xx (e.g. model not pulled) won't heal on retry — fail fast.
            raise OllamaUnavailable(str(exc)) from exc

    def _narrate_once(self, system: str, prompt: str) -> str:
        try:
            resp = self._client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    # num_predict caps thinking + content COMBINED for a
                    # reasoning model. 1200 was exhausted by chain-of-thought
                    # on data-heavy states (CT/KY/MI/TX 2026-07-10), returning
                    # empty content after retries — keep generous headroom.
                    "options": {"temperature": 0.2, "num_predict": 4000},
                },
            )
        except httpx.TransportError as exc:
            raise _RetryableError(f"transport error: {exc}") from exc
        if resp.status_code >= 500:
            raise _RetryableError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        resp.raise_for_status()
        try:
            message = resp.json().get("message") or {}
        except ValueError as exc:
            raise _RetryableError(f"non-JSON response: {exc}") from exc
        # gpt-oss is a reasoning model: Ollama returns its chain of thought in
        # message.thinking, which we ignore — content alone is the narrative.
        content = message.get("content") or ""
        if not content.strip():
            raise _RetryableError("empty narrative content")
        return content


def build_ollama_client() -> OllamaClient:
    """Construct the real client from OLLAMA_BASE_URL / OLLAMA_MODEL env."""
    return OllamaClient(
        base_url=os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL),
        model=os.getenv("OLLAMA_MODEL", DEFAULT_MODEL),
    )
