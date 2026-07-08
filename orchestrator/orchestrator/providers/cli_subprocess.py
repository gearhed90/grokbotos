"""Shared base for providers that shell out to an official, already-
authenticated vendor CLI instead of touching its stored credentials.

This is the correct pattern for "install the CLI, log in with your own
account, it just works" (what the user actually asked for): the vendor's
own binary handles auth entirely internally -- we never read a token file,
never call the vendor's HTTP API directly, never touch OAuth at all. We
just run `<cli> -p "<prompt>"` the same way a human would from their
terminal, and read stdout. This is categorically different from
providers/cloud_oauth.py (we'd be requesting our own OAuth grant) or from
directly parsing a credential cache file and hitting the vendor's REST API
ourselves -- both of those involve us handling credentials that belong to
the vendor's own client; this doesn't.

Login-state detection has no reliable side-effect-free check across CLIs
in general, so `ensure_ready()` runs a cheap real prompt as a smoke test
and treats failure as "not logged in". That smoke test costs one real
model call the first time; the READY result is cached for the life of
this object afterward.
"""

from __future__ import annotations

import json
import subprocess
from typing import Callable

from .base import ExternalLoginRequired, LLMProvider, ProviderNotReady, ProviderStatus

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _real_run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=120)


class CliSubprocessProvider(LLMProvider):
    """Subclasses set provider_id/cli_binary/login_command/install_argv and
    only need to implement _build_prompt_argv() if their CLI's flags for
    non-interactive single-shot prompting differ from `<cli> -p <prompt>`."""

    cli_binary: str
    login_command: str
    install_argv: list[str] | None = None  # None if there's nothing to auto-install

    def __init__(self, run: Runner = _real_run):
        self._run = run
        self._verified_ready = False

    def status(self) -> ProviderStatus:
        if self._verified_ready:
            return ProviderStatus.READY
        if not self._binary_present():
            return ProviderStatus.ERROR
        return ProviderStatus.AUTH_REQUIRED  # unknown until a real call succeeds

    def ensure_ready(self) -> None:
        if self._verified_ready:
            return

        if not self._binary_present():
            if self.install_argv is None:
                raise ExternalLoginRequired(
                    self.provider_id, self.login_command, detail=f"'{self.cli_binary}' not found on PATH"
                )
            result = self._run(self.install_argv)
            if result.returncode != 0 or not self._binary_present():
                raise ExternalLoginRequired(
                    self.provider_id,
                    self.login_command,
                    detail=f"install failed ({' '.join(self.install_argv)}): {result.stderr.strip()}",
                )

        smoke = self._run(self._build_prompt_argv("Reply with the single word: ok"))
        if smoke.returncode != 0:
            raise ExternalLoginRequired(
                self.provider_id,
                self.login_command,
                detail=f"'{self.cli_binary}' isn't logged in yet: {smoke.stderr.strip()}",
            )
        self._verified_ready = True

    def complete_json(self, prompt: str, schema: dict) -> dict:
        if not self._verified_ready:
            raise ProviderNotReady(f"{self.provider_id}: call ensure_ready() first")

        schema_instruction = (
            "Respond with ONLY valid JSON matching this schema, no other text:\n" + json.dumps(schema)
        )
        result = self._run(self._build_prompt_argv(f"{schema_instruction}\n\n{prompt}"))
        if result.returncode != 0:
            raise ProviderNotReady(f"{self.provider_id}: CLI call failed: {result.stderr.strip()}")
        return json.loads(result.stdout.strip())

    def _binary_present(self) -> bool:
        try:
            result = self._run([self.cli_binary, "--version"])
        except FileNotFoundError:
            return False
        return result.returncode == 0

    def _build_prompt_argv(self, prompt: str) -> list[str]:
        return [self.cli_binary, "-p", prompt]
