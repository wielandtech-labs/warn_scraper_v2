"""Tests for canonical-host redirects (warn_v2.api.canonical)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from warn_v2.api.canonical import CanonicalHostMiddleware, redirect_hosts

CANONICAL = "https://warnindex.com"
REDIRECTED = ["www.warnindex.com", "warnindex.net", "warn.wielandtech.com"]


def _client(hosts=REDIRECTED, canonical=CANONICAL) -> TestClient:
    """A minimal app wrapped in the middleware, with an echo route at any path."""
    app = FastAPI()
    app.add_middleware(CanonicalHostMiddleware, hosts=hosts, canonical=canonical)

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    def echo() -> dict:
        return {"served": True}

    return TestClient(app, follow_redirects=False)


# --- redirect_hosts() parsing ------------------------------------------------

def test_redirect_hosts_unset_is_empty(monkeypatch):
    monkeypatch.delenv("REDIRECT_HOSTS", raising=False)
    assert redirect_hosts() == frozenset()


def test_redirect_hosts_parses_and_normalises(monkeypatch):
    monkeypatch.setenv("REDIRECT_HOSTS", " WWW.Warnindex.com , warnindex.net ,, ")
    assert redirect_hosts() == frozenset({"www.warnindex.com", "warnindex.net"})


# --- redirecting -------------------------------------------------------------

@pytest.mark.parametrize("host", REDIRECTED)
def test_listed_host_redirects_to_canonical(host):
    resp = _client().get("/notices", headers={"host": host})
    assert resp.status_code == 301
    assert resp.headers["location"] == "https://warnindex.com/notices"


def test_redirect_preserves_path_and_query():
    resp = _client().get(
        "/states/CA?page=2&q=acme+corp", headers={"host": "warn.wielandtech.com"}
    )
    assert resp.status_code == 301
    assert (
        resp.headers["location"]
        == "https://warnindex.com/states/CA?page=2&q=acme+corp"
    )


def test_redirect_keeps_the_port_out_of_the_host_match():
    resp = _client().get("/", headers={"host": "warnindex.net:8000"})
    assert resp.status_code == 301
    assert resp.headers["location"] == "https://warnindex.com/"


def test_post_gets_308_so_the_method_and_body_survive():
    resp = _client().post("/api/subscriptions", headers={"host": "warnindex.net"})
    assert resp.status_code == 308
    assert resp.headers["location"] == "https://warnindex.com/api/subscriptions"


# --- passing through ---------------------------------------------------------

def test_canonical_host_is_served_not_redirected():
    resp = _client().get("/notices", headers={"host": "warnindex.com"})
    assert resp.status_code == 200


def test_unlisted_host_is_served():
    """The kubelet probe and Prometheus scrape case: Host is the pod IP.

    Anything not explicitly listed must be served, or a 301 fails the readiness
    probe and the pod never goes Ready.
    """
    resp = _client().get("/healthz", headers={"host": "10.42.1.7:8000"})
    assert resp.status_code == 200


def test_acme_challenge_is_never_redirected():
    """A 301 here would surface as an unrenewed certificate two months later."""
    resp = _client().get(
        "/.well-known/acme-challenge/tok3n", headers={"host": "warnindex.net"}
    )
    assert resp.status_code == 200


def test_empty_host_set_is_inert():
    resp = _client(hosts=[]).get("/notices", headers={"host": "warn.wielandtech.com"})
    assert resp.status_code == 200


def test_canonical_host_in_the_list_does_not_loop():
    """A misconfigured REDIRECT_HOSTS must not make the canonical host self-redirect."""
    client = _client(hosts=[*REDIRECTED, "warnindex.com"])
    assert client.get("/", headers={"host": "warnindex.com"}).status_code == 200
    assert client.get("/", headers={"host": "warnindex.net"}).status_code == 301


# --- wiring into the real app ------------------------------------------------

def test_create_app_wires_the_middleware_from_the_environment(monkeypatch):
    monkeypatch.setenv("REDIRECT_HOSTS", "warn.wielandtech.com")
    monkeypatch.setenv("SITE_BASE_URL", "https://warnindex.com")
    from warn_v2.api import create_app

    client = TestClient(create_app(), follow_redirects=False)
    assert client.get("/healthz", headers={"host": "warn.wielandtech.com"}).status_code == 301
    assert client.get("/healthz", headers={"host": "warnindex.com"}).status_code == 200


def test_create_app_is_inert_without_redirect_hosts(monkeypatch):
    monkeypatch.delenv("REDIRECT_HOSTS", raising=False)
    from warn_v2.api import create_app

    client = TestClient(create_app(), follow_redirects=False)
    assert client.get("/healthz", headers={"host": "warn.wielandtech.com"}).status_code == 200
