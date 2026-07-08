"""Small shared HTTP helpers for dev_agent's registry API calls.

Every dev_agent module takes `http_get`/`http_post` as injectable
parameters defaulting to these -- same pattern as providers/local_ollama.py
and providers/cloud_oauth.py -- so tests never hit the real network.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

USER_AGENT = "AI-OS-DevAgent/0.1 (https://github.com/head77x/oais)"


def real_get(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - caller supplies fixed registry URLs
        return json.loads(resp.read().decode())


def real_post_json(url: str, body: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - caller supplies fixed registry URLs
        return json.loads(resp.read().decode())


def urlencode(params: dict) -> str:
    return urllib.parse.urlencode(params)
