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
import os
import subprocess
from typing import Callable

from .base import ExternalLoginRequired, LLMProvider, ProviderNotReady, ProviderStatus

Runner = Callable[[list[str]], subprocess.CompletedProcess]


class CliSubprocessProvider(LLMProvider):
    """Subclasses set provider_id/cli_binary/login_command/install_argv and
    only need to implement _build_prompt_argv() if their CLI's flags for
    non-interactive single-shot prompting differ from `<cli> -p <prompt>`.

    `extra_env`/`set_env()` exist for providers whose only headless-friendly
    auth path is an env var carrying a pre-generated token (Claude:
    `CLAUDE_CODE_OAUTH_TOKEN`, see providers/claude_cli.py) rather than a
    device-code flow the CLI can drive itself.
    """

    cli_binary: str
    login_command: str
    install_argv: list[str] | None = None  # None if there's nothing to auto-install

    def __init__(
        self,
        run: Runner | None = None,
        extra_env: dict[str, str] | None = None,
        log: "Callable[[str], None] | None" = None,
    ):
        self._run = run or self._default_run
        self._verified_ready = False
        self._extra_env: dict[str, str] = dict(extra_env or {})
        # Fed to the shell UI's live log panel (webshell/logbuf.py) so
        # "연결 중..." isn't the only thing the user sees while this runs a
        # real install/login subprocess that can take a while -- no-op by
        # default so every other caller (onboarding_cli.py, tests) is
        # unaffected.
        self._log: Callable[[str], None] = log or (lambda _msg: None)

    def set_env(self, key: str, value: str) -> None:
        """Add/override an environment variable for every subprocess call
        this provider makes from here on. Does not touch the parent
        process's real environment."""
        self._extra_env[key] = value
        self._verified_ready = False  # re-verify with the new credential

    def _default_run(self, argv: list[str]) -> subprocess.CompletedProcess:
        env = {**os.environ, **self._extra_env} if self._extra_env else None
        return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=120, env=env)

    def interactive_login(self) -> bool:
        """Run `login_command` with the CLI's real stdio (not captured), so
        a device-code URL/prompt (Grok) is visible on screen and reaches
        the real terminal, blocking until the CLI exits. Not something a
        unit test can meaningfully fake -- this needs a real terminal and
        a human on the other end of the login URL; verify on a real
        machine. Returns whether the login command itself exited 0
        (callers should still confirm with ensure_ready() after)."""
        argv = self.login_command.split()
        env = {**os.environ, **self._extra_env} if self._extra_env else None
        self._log(f"[{self.cli_binary}] 실행: {self.login_command} (브라우저가 열리면 로그인을 완료하세요)")
        result = subprocess.run(argv, env=env, timeout=600)
        self._log(f"[{self.cli_binary}] {self.login_command} 종료 (코드 {result.returncode})")
        return result.returncode == 0

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
            self._log(f"[{self.cli_binary}] 설치 중: {' '.join(self.install_argv)}")
            result = self._run(self.install_argv)
            if result.returncode != 0 or not self._binary_present():
                self._log(f"[{self.cli_binary}] 설치 실패 (종료 코드 {result.returncode})")
                raise ExternalLoginRequired(
                    self.provider_id,
                    self.login_command,
                    detail=f"install failed ({' '.join(self.install_argv)}): {result.stderr.strip()}",
                )
            self._log(f"[{self.cli_binary}] 설치 완료")

        self._log(f"[{self.cli_binary}] 로그인 상태 확인 중...")
        smoke = self._run(self._build_prompt_argv("Reply with the single word: ok"))
        if smoke.returncode != 0:
            self._log(f"[{self.cli_binary}] 로그인 필요 (확인 실패: {smoke.stderr.strip()[:200]})")
            raise ExternalLoginRequired(
                self.provider_id,
                self.login_command,
                detail=f"'{self.cli_binary}' isn't logged in yet: {smoke.stderr.strip()}",
            )
        self._log(f"[{self.cli_binary}] 준비 완료")
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
