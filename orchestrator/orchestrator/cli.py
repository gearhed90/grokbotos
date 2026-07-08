"""Manual smoke-test entrypoint. Not the real Phase 4 shell (text/voice
fullscreen UI) -- just a CLI to exercise the pipeline while that doesn't
exist yet."""

from __future__ import annotations

import argparse
import datetime
import sys

from .llm import StubIntentAnalyzer
from .registry.db import AppRecord, AppRegistry
from .state_machine import Orchestrator, OrchestratorNotReady, OrchestratorTimeout


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
    args = parser.parse_args(argv)

    registry = AppRegistry(args.db)
    if args.seed_demo_app:
        _seed_demo_app(registry)

    orchestrator = Orchestrator(registry=registry, intent_analyzer=StubIntentAnalyzer())

    try:
        result = orchestrator.process(args.prompt)
    except (OrchestratorNotReady, OrchestratorTimeout) as exc:
        print(f"[{type(exc).__name__}] {exc}", file=sys.stderr)
        return 1
    finally:
        registry.close()

    print(f"status={result.status} final_state={result.final_state.name}")
    print(f"summary: {result.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
