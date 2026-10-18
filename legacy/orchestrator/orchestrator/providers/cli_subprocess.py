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
import threading
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

    # A real `npm install -g` of a CLI package (registry resolution,
    # download, any native/postinstall steps) routinely takes well over
    # 120s on a constrained VM's shared virtio-net -- confirmed via the
    # live log panel: a real install hit `TimeoutExpired` at exactly 120s
    # (2026-07-11, docs/DECISIONS.md). Prompt calls (`<cli> -p ...`)
    # should be much faster in practice; keeping their timeout tighter
    # means a genuinely hung CLI still fails fast instead of blocking the
    # whole connect flow for 10 minutes.
    _INSTALL_TIMEOUT_SECONDS = 600
    _PROMPT_TIMEOUT_SECONDS = 120

    def _default_run(self, argv: list[str]) -> subprocess.CompletedProcess:
        env = {**os.environ, **self._extra_env} if self._extra_env else None
        timeout = self._INSTALL_TIMEOUT_SECONDS if argv == self.install_argv else self._PROMPT_TIMEOUT_SECONDS
        return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=timeout, env=env)

    def interactive_login(self) -> bool:
        """Run `login_command`, streaming its output line by line into
        both `_log()` (the shell UI's live log panel) and real stdout.

        Used to inherit stdio uncaptured on the theory that a human would
        be watching a real terminal -- but in the GUI shell
        (webshell_cli.py), that terminal doesn't exist: sway redirects
        this whole process's stdio to a log file nobody's watching. A
        real login failure (e.g. `claude login` exiting non-zero) showed
        up in the log panel as a bare exit code with zero context
        (2026-07-11, docs/DECISIONS.md) -- capturing and re-emitting each
        line through `_log()` fixes that, and is also the only way a
        device-code URL/prompt (Grok) reaches the user at all in that
        path. Still `print()`s each line too, so `onboarding_cli.py`'s
        real-terminal fallback keeps seeing it live as before. Returns
        whether the login command itself exited 0 (callers should still
        confirm with ensure_ready() after)."""
        argv = self.login_command.split()
        env = {**os.environ, **self._extra_env} if self._extra_env else None
        self._log(f"[{self.cli_binary}] 실행: {self.login_command} (브라우저가 열리면 로그인을 완료하세요)")

        proc = subprocess.Popen(
            argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )

        def _pump() -> None:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line:
                    self._log(f"[{self.cli_binary}] {line}")
                    print(line, flush=True)

        pump_thread = threading.Thread(target=_pump, daemon=True)
        pump_thread.start()
        try:
            proc.wait(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            self._log(f"[{self.cli_binary}] {self.login_command} 시간 초과 (600초)")
            raise
        pump_thread.join(timeout=5)  # let any already-produced output finish logging

        self._log(f"[{self.cli_binary}] {self.login_command} 종료 (코드 {proc.returncode})")
        return proc.returncode == 0

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
                # stderr, not just the exit code -- an exit code alone
                # (e.g. npm's 254) doesn't say whether this was a
                # permission error, a network failure, or something else
                # entirely, and guessing wasted a full round-trip before
                # (2026-07-11, docs/DECISIONS.md).
                stderr_snippet = (result.stderr or "").strip()[:300]
                self._log(f"[{self.cli_binary}] 설치 실패 (종료 코드 {result.returncode}): {stderr_snippet}")
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
