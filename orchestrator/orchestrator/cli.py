"""Manual smoke-test entrypoint. Not the real Phase 4 shell (text/voice
fullscreen UI) -- just a CLI to exercise the pipeline while that doesn't
exist yet."""

from __future__ import annotations

import argparse
import datetime
import sys

from .llm import StubIntentAnalyzer
from .providers.base import ExternalLoginRequired, ProviderNotReady
from .providers.claude_cli import ClaudeCliProvider
from .providers.xai_grok import GrokCliProvider
from .registry.db import AppRecord, AppRegistry
from .state_machine import DevelopmentPending, Orchestrator, OrchestratorNotReady, OrchestratorTimeout

_DEV_PROVIDERS = {"claude": ClaudeCliProvider, "grok": GrokCliProvider}


def _seed_demo_app(registry: AppRegistry) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    registry.register(
        AppRecord(
            app_id="demo.hello",
            name="Hello Demo App",
            description="Prints a greeting. Exists only to exercise the EXECUTE_EXISTING path.",
            capability_tags=["hello", "demo", "greeting"],
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "string"},
            exec_manifest={
                "entrypoint": "echo hello",
                "runtime": "shell",
                "sandbox_profile_id": "none",
                "dependencies": [],
            },
            creation_source="generated",
            version="0.1.0",
            created_at=now,
            updated_at=now,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="User request text")
    parser.add_argument(
        "--seed-demo-app",
        action="store_true",
        help="Register a fake app first so a tag match is possible",
    )
    parser.add_argument("--db", default=":memory:", help="SQLite path (default: in-memory)")
    parser.add_argument(
        "--dev-provider",
        choices=sorted(_DEV_PROVIDERS),
        default=None,
        help=(
            "Enable PLAN->DEVELOP (2.5/2.6) on registry-search misses by wrapping the "
            "named official CLI (must already be installed and logged in -- "
            "`claude login` / `grok login`). Makes real network + LLM calls. "
            "Omit to keep the old behavior (raises OrchestratorNotReady on a miss)."
        ),
    )
    args = parser.parse_args(argv)

    registry = AppRegistry(args.db)
    if args.seed_demo_app:
        _seed_demo_app(registry)

    dev_provider = None
    if args.dev_provider:
        dev_provider = _DEV_PROVIDERS[args.dev_provider]()
        try:
            dev_provider.ensure_ready()
        except ExternalLoginRequired as exc:
            print(f"[{type(exc).__name__}] {exc}", file=sys.stderr)
            registry.close()
            return 1

    orchestrator = Orchestrator(
        registry=registry, intent_analyzer=StubIntentAnalyzer(), dev_provider=dev_provider
    )

    try:
        result = orchestrator.process(args.prompt)
    except DevelopmentPending as exc:
        dev = exc.development_result
        print(f"[{type(exc).__name__}] path={dev.path.name} reason={dev.reason}", file=sys.stderr)
        if dev.exec_manifest:
            print(f"exec_manifest: {dev.exec_manifest}", file=sys.stderr)
        return 1
    except (OrchestratorNotReady, OrchestratorTimeout, ProviderNotReady) as exc:
        print(f"[{type(exc).__name__}] {exc}", file=sys.stderr)
        return 1
    finally:
        registry.close()

    print(f"status={result.status} final_state={result.final_state.name}")
    print(f"summary: {result.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
