import subprocess
import unittest

from orchestrator.providers.claude_cli import ClaudeCliProvider


def _ok(argv, stdout=""):
    return subprocess.CompletedProcess(argv, returncode=0, stdout=stdout, stderr="")


class TestClaudeCliProvider(unittest.TestCase):
    def test_config(self):
        self.assertEqual(ClaudeCliProvider.cli_binary, "claude")
        self.assertEqual(ClaudeCliProvider.login_command, "claude login")
        self.assertEqual(ClaudeCliProvider.install_argv, ["npm", "install", "-g", "@anthropic-ai/claude-code"])

    def test_end_to_end_with_fake_run(self):
        def fake_run(argv):
            if argv == ["claude", "--version"]:
                return _ok(argv)
            if "-p" in argv:
                prompt = argv[argv.index("-p") + 1]
                if prompt.strip().endswith("ok"):
                    return _ok(argv, stdout="ok")
                return _ok(argv, stdout='{"goal": "summarize"}')
            return _ok(argv)

        provider = ClaudeCliProvider(run=fake_run)
        provider.ensure_ready()

        result = provider.complete_json("summarize this", schema={"type": "object"})

        self.assertEqual(result, {"goal": "summarize"})


if __name__ == "__main__":
    unittest.main()
