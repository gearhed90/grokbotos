# orchestrator (Phase 2 prototype)

Local prototype of the closed-loop pipeline from `docs/ROADMAP.md` Phase 2:

```
RECEIVED -> INTENT_ANALYSIS -> REGISTRY_SEARCH
  -> EXECUTE_EXISTING -> DELIVER_RESULT
  -> PLAN -> DEVELOP -> TEST -> (REGISTER_AND_EXECUTE -> DELIVER_RESULT | RETRY_DEVELOP)
```

This is intentionally **not** wired into the OS image yet (that's Phase 5).
It's a standalone Python package so the pipeline logic can be iterated on and
tested without needing a bootc build or a booted VM.

Stdlib only, on purpose -- whatever this package depends on eventually has to
be `dnf install`-able (or vendored) inside the Containerfile in Phase 5, so
external deps are added deliberately, not by default.

## What's real vs. stubbed right now

| Stage | Status |
|---|---|
| 2.2 Task Spec schema | Implemented (`task_spec.py`) |
| 2.2 LLM-based intent analysis | **Stubbed** -- `llm.py` has a `StubIntentAnalyzer` that does keyword extraction, not an LLM call. No cloud/local/hybrid LLM provider has been chosen yet (see open question in `docs/ROADMAP.md`) |
| 2.3 Registry DB schema | Implemented (`registry/schema.sql`), matches the field list in `ROADMAP.md` 2.3 exactly |
| 2.3 Tier-1 capability-tag filter | Implemented (`registry/matcher.py`) |
| 2.3 Tier-2 embedding similarity | **Not implemented** -- no embedding model chosen yet |
| 2.3 Tier-3 LLM re-verification | **Not implemented** -- depends on the LLM decision above |
| 2.4 Execute existing app | **Stubbed** -- returns a fake result, no Phase 3 sandbox to call into yet |
| 2.5-2.8 Plan/Develop/Test/Register | **Not implemented** -- `state_machine.py` raises `NotImplementedError` with a clear message when a request falls through to this path, instead of pretending to succeed |
| 2.9 Result format | Implemented (`ResultEnvelope` in `state_machine.py`) |
| Closed-loop controller / state machine | Implemented (`state_machine.py`), including retry-count and simple wall-clock timeout guards |

## Running it

```bash
cd orchestrator
python3 -m orchestrator.cli "이미지에서 텍스트 추출해줘"     # no matching app -> NotImplementedError (expected, honest)
python3 -m orchestrator.cli --seed-demo-app "hello demo app"  # seeds a matching app first -> EXECUTE_EXISTING path
```

## Tests

```bash
cd orchestrator
python3 -m unittest discover -s tests -v
```
