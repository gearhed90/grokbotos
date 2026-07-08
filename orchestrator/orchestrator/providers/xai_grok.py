"""xAI/Grok via the official Grok CLI, run as a subprocess.

Same pattern as claude_cli.py: the user runs `grok login` themselves
(which caches OAuth credentials at `~/.grok/auth.json` -- confirmed via
`@xai-official/grok`'s own docs), and this provider never reads that file
or calls `api.x.ai` directly. It shells out to `grok -p "<prompt>"`, the
CLI's own documented non-interactive mode (its README's own smoke-test
example is literally `grok --no-auto-update -p "Say ok."`), and reads
stdout. `--no-auto-update` is passed on every call so a background CLI
self-update never interrupts a synchronous prompt.
"""

from __future__ import annotations

from .cli_subprocess import CliSubprocessProvider


class GrokCliProvider(CliSubprocessProvider):
    provider_id = "xai-grok"
    cli_binary = "grok"
    login_command = "grok login"
    install_argv = ["npm", "install", "-g", "@xai-official/grok"]

    def _build_prompt_argv(self, prompt: str) -> list[str]:
        return [self.cli_binary, "--no-auto-update", "-p", prompt]
