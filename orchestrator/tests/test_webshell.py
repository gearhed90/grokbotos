import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from orchestrator.providers.base import ExternalLoginRequired, ModelNotInstalled
from orchestrator.registry.db import AppRecord, AppRegistry
from orchestrator.webshell import api
from orchestrator.webshell.connect import run_connect, run_connect_token
from orchestrator.webshell.server import build_server
from orchestrator.webshell.state import ConnectionState


class _FakeProvider:
    provider_id = "fake"

    def __init__(self, model_id=None):
        self.model_id = model_id


def _register_app(registry, app_id, tags):
    registry.register(
        AppRecord(
            app_id=app_id,
            name=app_id,
            description="test app",
            capability_tags=tags,
            input_schema={"type": "object"},
            output_schema={"type": "string"},
            exec_manifest={"entrypoint": "true", "runtime": "shell", "sandbox_profile_id": "none", "dependencies": []},
            creation_source="generated",
            version="0.1.0",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
    )


class TestConnectionState(unittest.TestCase):
    def test_initial_snapshot_is_disconnected(self):
        state = ConnectionState()
        self.assertEqual(
            state.snapshot(),
            {"connected": False, "choice_id": None, "connecting": None, "error": None, "needs_token": False},
        )

    def test_start_connecting_clears_prior_error(self):
        state = ConnectionState()
        state.set_error("boom", needs_token=True)

        state.start_connecting("claude")

        snap = state.snapshot()
        self.assertEqual(snap["connecting"], "claude")
        self.assertIsNone(snap["error"])
        self.assertFalse(snap["needs_token"])

    def test_set_connected_reports_connected_true(self):
        state = ConnectionState()
        provider = _FakeProvider()

        state.set_connected("grok", provider)

        snap = state.snapshot()
        self.assertTrue(snap["connected"])
        self.assertEqual(snap["choice_id"], "grok")
        self.assertIsNone(snap["connecting"])

    def test_set_error_reports_disconnected_with_message(self):
        state = ConnectionState()

        state.set_error("nope", needs_token=True)

        snap = state.snapshot()
        self.assertFalse(snap["connected"])
        self.assertEqual(snap["error"], "nope")
        self.assertTrue(snap["needs_token"])


class TestRunConnect(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = Path(self._tmp.name) / "provider.json"

    def test_success_saves_connection_and_marks_connected(self):
        state = ConnectionState()
        provider = _FakeProvider(model_id="llama3")

        run_connect(
            "ollama", state, self.config_path,
            connectors={"ollama": lambda **kw: provider},
        )

        snap = state.snapshot()
        self.assertTrue(snap["connected"])
        self.assertEqual(snap["choice_id"], "ollama")
        self.assertTrue(self.config_path.exists())
        saved = json.loads(self.config_path.read_text())
        self.assertEqual(saved["model_id"], "llama3")

    def test_closes_any_new_firefox_window_a_login_flow_opened(self):
        """Real bug: `claude auth login` opens a real Firefox window for
        OAuth; its own success page says "you can now close this window"
        but this kiosk has no title bar/chrome to do that with, leaving
        the user stuck unable to get back to the shell (2026-07-11,
        docs/DECISIONS.md). run_connect() must close whatever new Firefox
        window showed up during the connector call, automatically."""
        import subprocess as _subprocess

        state = ConnectionState()
        swaymsg_calls = []
        get_tree_call_count = [0]

        def _tree_result(*firefox_ids):
            payload = json.dumps(
                {
                    "id": 0,
                    "nodes": [{"id": i, "app_id": "firefox", "nodes": [], "floating_nodes": []} for i in firefox_ids],
                    "floating_nodes": [],
                }
            )
            return _subprocess.CompletedProcess([], returncode=0, stdout=payload, stderr="")

        def fake_swaymsg_run(argv, **kw):
            swaymsg_calls.append(argv)
            if argv == ["swaymsg", "-t", "get_tree"]:
                get_tree_call_count[0] += 1
                # Before the connector call: just the kiosk window (id 1).
                # After: a new OAuth popup (id 2) has also appeared.
                return _tree_result(1) if get_tree_call_count[0] == 1 else _tree_result(1, 2)
            return _subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")

        run_connect(
            "claude", state, self.config_path,
            connectors={"claude": lambda **kw: _FakeProvider()},
            swaymsg_run=fake_swaymsg_run,
        )

        kill_calls = [c for c in swaymsg_calls if c[-1] == "kill"]
        self.assertEqual(kill_calls, [["swaymsg", "[con_id=2]", "kill"]])

    def test_external_login_required_for_claude_sets_needs_token(self):
        state = ConnectionState()

        def _raise(**kw):
            raise ExternalLoginRequired("claude", "claude login", detail="denied")

        run_connect("claude", state, self.config_path, connectors={"claude": _raise})

        snap = state.snapshot()
        self.assertFalse(snap["connected"])
        self.assertTrue(snap["needs_token"])
        self.assertIn("claude login", snap["error"])

    def test_external_login_required_for_grok_does_not_set_needs_token(self):
        state = ConnectionState()

        def _raise(**kw):
            raise ExternalLoginRequired("grok", "grok login")

        run_connect("grok", state, self.config_path, connectors={"grok": _raise})

        self.assertFalse(state.snapshot()["needs_token"])

    def test_provider_not_ready_sets_error(self):
        state = ConnectionState()

        def _raise(**kw):
            raise ModelNotInstalled("ollama", "llama3", detail="pull failed")

        run_connect("ollama", state, self.config_path, connectors={"ollama": _raise})

        snap = state.snapshot()
        self.assertFalse(snap["connected"])
        self.assertIn("llama3", snap["error"])

    def test_unknown_provider_sets_error_without_raising(self):
        state = ConnectionState()

        run_connect("nope", state, self.config_path, connectors={})

        self.assertIn("unknown provider", state.snapshot()["error"])

    def test_custom_without_cli_binary_sets_error(self):
        state = ConnectionState()

        run_connect("custom", state, self.config_path, connectors={"custom": lambda **kw: _FakeProvider()})

        self.assertIn("cli_binary", state.snapshot()["error"])

    def test_custom_saves_cli_fields(self):
        state = ConnectionState()
        provider = _FakeProvider()
        provider.cli_binary = "mycli"
        provider.login_command = "mycli login"
        provider.install_argv = None

        run_connect(
            "custom", state, self.config_path,
            cli_binary="mycli", login_command="mycli login",
            connectors={"custom": lambda **kw: provider},
        )

        saved = json.loads(self.config_path.read_text())
        self.assertEqual(saved["custom_cli_binary"], "mycli")

    def test_unexpected_exception_surfaces_as_error_instead_of_hanging(self):
        """The actual 2026-07-11 bug: npm missing from the image made
        install_argv raise a bare FileNotFoundError, which isn't
        ExternalLoginRequired/ProviderNotReady -- before this catch-all,
        that silently killed the background thread and left the UI
        showing "connecting" forever with no error ever surfaced."""
        state = ConnectionState()

        def _raise(**kw):
            raise FileNotFoundError("[Errno 2] No such file or directory: 'npm'")

        run_connect("claude", state, self.config_path, connectors={"claude": _raise})

        snap = state.snapshot()
        self.assertFalse(snap["connected"])
        self.assertIsNone(snap["connecting"])
        self.assertIn("npm", snap["error"])


class TestRunConnectToken(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = Path(self._tmp.name) / "provider.json"

    def test_success_marks_connected(self):
        state = ConnectionState()
        provider = _FakeProvider()

        run_connect_token("claude", "tok-123", state, self.config_path, token_connector=lambda tok, log=None: provider)

        self.assertTrue(state.snapshot()["connected"])

    def test_failure_keeps_needs_token(self):
        state = ConnectionState()

        def _raise(tok, log=None):
            raise ExternalLoginRequired("claude", "claude login", detail="bad token")

        run_connect_token("claude", "tok-bad", state, self.config_path, token_connector=_raise)

        snap = state.snapshot()
        self.assertFalse(snap["connected"])
        self.assertTrue(snap["needs_token"])

    def test_non_claude_provider_rejected(self):
        state = ConnectionState()

        run_connect_token("grok", "tok", state, self.config_path)

        self.assertIn("claude", state.snapshot()["error"])

    def test_unexpected_exception_surfaces_as_error_instead_of_hanging(self):
        state = ConnectionState()

        def _raise(tok, log=None):
            raise RuntimeError("boom")

        run_connect_token("claude", "tok", state, self.config_path, token_connector=_raise)

        snap = state.snapshot()
        self.assertFalse(snap["connected"])
        self.assertIsNone(snap["connecting"])
        self.assertIn("boom", snap["error"])


class TestApiPayloads(unittest.TestCase):
    def setUp(self):
        self.registry = AppRegistry(":memory:")
        self.addCleanup(self.registry.close)

    def test_apps_payload_lists_registered_apps(self):
        _register_app(self.registry, "app.a", ["alpha"])

        payload = api.apps_payload(self.registry)

        self.assertEqual([a["app_id"] for a in payload["apps"]], ["app.a"])

    def test_apps_payload_empty_when_nothing_registered(self):
        self.assertEqual(api.apps_payload(self.registry), {"apps": []})

    def test_prompt_payload_without_connected_provider_returns_error(self):
        state = ConnectionState()

        result = api.prompt_payload(state, self.registry, "do something")

        self.assertEqual(result["status"], "error")
        self.assertIn("LLM", result["message"])

    def test_prompt_payload_executes_matching_app(self):
        _register_app(self.registry, "app.existing", ["translate", "text"])
        state = ConnectionState()
        state.set_connected("claude", _CompleteJsonProvider(
            {"raw_prompt": "x", "goal": "translate", "capability_tags": ["translate", "text"]}
        ))

        result = api.prompt_payload(state, self.registry, "translate this")

        self.assertEqual(result["status"], "success")

    def test_prompt_payload_needs_clarification(self):
        state = ConnectionState()
        state.set_connected("claude", _CompleteJsonProvider(
            {"raw_prompt": "x", "goal": "", "needs_clarification": True, "clarification_questions": ["뭘 원하세요?"]}
        ))

        result = api.prompt_payload(state, self.registry, "do the thing")

        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["questions"], ["뭘 원하세요?"])

    def test_prompt_payload_adapter_band_returns_generic_error(self):
        _register_app(self.registry, "app.partial", ["translate", "summarize", "pdf"])
        state = ConnectionState()
        state.set_connected("claude", _CompleteJsonProvider(
            {"raw_prompt": "x", "goal": "x", "capability_tags": ["translate", "summarize", "ocr"]}
        ))

        result = api.prompt_payload(state, self.registry, "ocr this pdf")

        self.assertEqual(result["status"], "error")


class _CompleteJsonProvider:
    provider_id = "fake"

    def __init__(self, response: dict):
        self._response = response

    def complete_json(self, prompt, schema):
        return dict(self._response)


class TestWebServerIntegration(unittest.TestCase):
    """Real socket, but only routes that never touch subprocesses/network."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = Path(self._tmp.name) / "provider.json"
        self.registry = AppRegistry(":memory:")
        self.addCleanup(self.registry.close)
        self.state = ConnectionState()
        self.server = build_server(self.state, self.registry, config_path=self.config_path)
        self.port = self.server.server_address[1]

        import threading

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as resp:
            return resp.status, resp.read()

    def _post(self, path, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())

    def test_index_serves_html(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>AI-OS</title>", body)

    def test_static_js_served_with_correct_content_type(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/static/app.js", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("javascript", resp.headers.get("Content-Type", ""))

    def test_static_path_traversal_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/static/../server.py")
        self.assertEqual(ctx.exception.code, 404)

    def test_logs_endpoint_reflects_dispatched_commands(self):
        self._post("/api/prompt", {"text": "/help"})

        status, body = self._get("/api/logs?after=-1")
        data = json.loads(body)

        self.assertEqual(status, 200)
        self.assertTrue(any("/help" in text for _id, text in data["entries"]))
        self.assertGreaterEqual(data["next_after"], 0)

    def test_status_endpoint_reflects_disconnected_state(self):
        code, body = self._get("/api/status")
        data = json.loads(body)
        self.assertEqual(code, 200)
        self.assertFalse(data["connected"])

    def test_choices_endpoint_lists_providers(self):
        code, body = self._get("/api/choices")
        data = json.loads(body)
        ids = {c["id"] for c in data["choices"]}
        self.assertEqual(ids, {"claude", "grok", "ollama", "custom"})

    def test_prompt_routes_slash_command_to_router(self):
        """Confirms /api/prompt -- the same endpoint a manually typed
        prompt uses -- also handles built-in commands, i.e. a tile click
        and hand-typed text really do go through one path."""
        status, data = self._post("/api/prompt", {"text": "/help"})

        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "success")
        self.assertIn("/llm", data["message"])

    def test_prompt_without_connection_returns_error_status(self):
        status, data = self._post("/api/prompt", {"text": "hello"})
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "error")

    def test_prompt_with_empty_text_returns_400(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/prompt", {"text": "  "})
        self.assertEqual(ctx.exception.code, 400)


class _CompletedProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode


class TestWebshellCliMain(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = Path(self._tmp.name) / "provider.json"
        self.registry_path = Path(self._tmp.name) / "registry.db"

    def test_launches_firefox_kiosk_against_bound_port_and_shuts_down(self):
        from orchestrator import webshell_cli

        calls = []

        def _fake_run(argv):
            calls.append(argv)
            return _CompletedProcess(returncode=0)

        webshell_cli.main(
            run=_fake_run, port=0, config_path=self.config_path, registry_path=self.registry_path
        )

        self.assertEqual(len(calls), 1)
        argv = calls[0]
        self.assertEqual(argv[:2], ["firefox", "--kiosk"])
        self.assertTrue(argv[2].startswith("http://127.0.0.1:"))

    def test_no_saved_connection_starts_disconnected(self):
        from orchestrator import webshell_cli

        seen_state = {}

        def _fake_run(argv):
            # by the time firefox would launch, the server thread is up and
            # the initial state has already been computed
            seen_state["connected"] = webshell_cli._initial_state(self.config_path).snapshot()["connected"]
            return _CompletedProcess(returncode=0)

        webshell_cli.main(
            run=_fake_run, port=0, config_path=self.config_path, registry_path=self.registry_path
        )

        self.assertFalse(seen_state["connected"])

    def test_firefox_crash_falls_back_to_text_shell(self):
        """The bug this guards against: sway's `exec` silently dying leaves
        a black screen with nothing visible and nothing to debug. If
        Firefox exits nonzero, something (the old text shell) must still
        launch rather than leaving the compositor showing nothing."""
        from orchestrator import webshell_cli

        calls = []

        def _fake_run(argv):
            calls.append(argv)
            if argv[0] == "firefox":
                return _CompletedProcess(returncode=1)
            return _CompletedProcess(returncode=0)

        webshell_cli.main(
            run=_fake_run, port=0, config_path=self.config_path, registry_path=self.registry_path
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "firefox")
        self.assertEqual(calls[1], webshell_cli.FALLBACK_ARGV)

    def test_firefox_binary_missing_falls_back_to_text_shell(self):
        from orchestrator import webshell_cli

        calls = []

        def _fake_run(argv):
            calls.append(argv)
            if argv[0] == "firefox":
                raise FileNotFoundError("no such file: firefox")
            return _CompletedProcess(returncode=0)

        webshell_cli.main(
            run=_fake_run, port=0, config_path=self.config_path, registry_path=self.registry_path
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], webshell_cli.FALLBACK_ARGV)

    def test_firefox_success_does_not_trigger_fallback(self):
        from orchestrator import webshell_cli

        calls = []

        def _fake_run(argv):
            calls.append(argv)
            return _CompletedProcess(returncode=0)

        webshell_cli.main(
            run=_fake_run, port=0, config_path=self.config_path, registry_path=self.registry_path
        )

        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
