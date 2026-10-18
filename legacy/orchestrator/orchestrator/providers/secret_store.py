"""Where provider API keys live.

Not a raw-API-key-in-a-config-file design: `SecretStore` is an interface so
the actual storage can be swapped without touching provider code.
`EnvSecretStore` (env var lookup) is what's implemented and tested here;
a real OS-keyring-backed store (`secretstorage`/`keyring` on Linux) is
Phase 4/5 work, once there's a shell UI to drive a "connect account" flow
and a decision on what ships in the Containerfile (ROADMAP.md 2.6 will
need dnf-installable dependencies for whatever's picked).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class SecretStore(ABC):
    @abstractmethod
    def get(self, name: str) -> str | None: ...


class EnvSecretStore(SecretStore):
    def get(self, name: str) -> str | None:
        return os.environ.get(name)
