"""Anthropic via the official Claude Code CLI, run as a subprocess.

The user logs in with their own account (`claude login`, Pro/Max/Team
subscription or Console API key -- whichever Claude Code itself supports)
exactly as they would on any machine. This provider never touches that
credential: it shells out to `claude -p "<prompt>"` and reads stdout, the
same interface a human runs from their terminal. See
providers/cli_subprocess.py's docstring for why this is a different (and
unproblematic) thing from directly reusing Claude Code's OAuth token
against the Messages API ourselves, which docs/DECISIONS.md documents as
against Anthropic's Consumer Terms of Service.

`providers/anthropic_api_key.py` (official `x-api-key` REST auth) remains
available as a fallback for setups without Claude Code installed --
mirroring how the Grok CLI itself falls back to `XAI_API_KEY`.

`claude login` itself needs a local browser to complete the OAuth
redirect (confirmed via Anthropic's own docs, code.claude.com/docs/en/authentication)
-- not available on this project's console-only OS (docs/DECISIONS.md).
`authenticate_with_token()` is the documented headless-friendly path
instead: run `claude setup-token` on a machine that *does* have a
browser, then feed the resulting token in here.
"""

from __future__ import annotations

from .cli_subprocess import CliSubprocessProvider

OAUTH_TOKEN_ENV_VAR = "CLAUDE_CODE_OAUTH_TOKEN"


class ClaudeCliProvider(CliSubprocessProvider):
    provider_id = "anthropic-claude-code"
    cli_binary = "claude"
    login_command = "claude login"
    install_argv = ["npm", "install", "-g", "@anthropic-ai/claude-code"]

    def authenticate_with_token(self, token: str) -> None:
        """Use a `claude setup-token` output instead of driving `claude
        login`'s browser flow (which needs a local browser this OS
        doesn't have). Per Anthropic's documented auth precedence,
        CLAUDE_CODE_OAUTH_TOKEN authenticates the CLI directly -- no
        interactive login step needed after this."""
        self.set_env(OAUTH_TOKEN_ENV_VAR, token)
