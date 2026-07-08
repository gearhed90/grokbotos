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
"""

from __future__ import annotations

from .cli_subprocess import CliSubprocessProvider


class ClaudeCliProvider(CliSubprocessProvider):
    provider_id = "anthropic-claude-code"
    cli_binary = "claude"
    login_command = "claude login"
    install_argv = ["npm", "install", "-g", "@anthropic-ai/claude-code"]
