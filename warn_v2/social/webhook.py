"""Incoming-webhook channels (Discord, Slack): one JSON POST per alert."""
from __future__ import annotations

import os

import httpx

# platform -> (env var holding the webhook URL, JSON key the service reads)
WEBHOOKS = {
    "discord": ("DISCORD_WEBHOOK_URL", "content"),
    "slack": ("SLACK_WEBHOOK_URL", "text"),
}


def configured(platform: str) -> bool:
    return bool(os.getenv(WEBHOOKS[platform][0]))


def payload(platform: str, text: str) -> dict[str, str]:
    return {WEBHOOKS[platform][1]: text}


def send(platform: str, text: str, client: httpx.Client) -> None:
    env, _key = WEBHOOKS[platform]
    client.post(os.environ[env], json=payload(platform, text)).raise_for_status()
