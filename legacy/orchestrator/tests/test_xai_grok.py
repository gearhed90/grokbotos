import subprocess
import unittest

from orchestrator.providers.xai_grok import GrokCliProvider


def _ok(argv, stdout=""):
    return subprocess.CompletedProcess(argv, returncode=0, stdout=stdout, stderr="")


class TestGrokCliProvider(unittest.TestCase):
    def test_config(self):
        self.assertEqual(GrokCliProvider.cli_binary, "grok")
        self.assertEqual(GrokCliProvider.login_command, "grok login")
        self.assertEqual(GrokCliProvider.install_argv, ["npm", "install", "-g", "@xai-official/grok"])

    def test_prompt_argv_includes_no_auto_update_flag(self):
        provider = GrokCliProvider(run=lambda argv: _ok(argv))

        self.assertEqual(
            provider._build_prompt_argv("hello"),
            ["grok", "--no-auto-update", "-p", "hello"],
        )

    def test_end_to_end_with_fake_run(self):
        calls = []

        def fake_run(argv):
            calls.append(argv)
            if argv == ["grok", "--version"]:
                return _ok(argv)
            if "-p" in argv:
                prompt = argv[argv.index("-p") + 1]
                if prompt.strip().endswith("ok"):
                    return _ok(argv, stdout="ok")
                return _ok(argv, stdout='{"goal": "translate"}')
            return _ok(argv)

        provider = GrokCliProvider(run=fake_run)
        provider.ensure_ready()

        result = provider.complete_json("translate this", schema={"type": "object"})

        self.assertEqual(result, {"goal": "translate"})
        self.assertTrue(any(c[:2] == ["grok", "--no-auto-update"] for c in calls))


if __name__ == "__main__":
    unittest.main()
