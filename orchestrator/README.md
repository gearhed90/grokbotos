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
| 2.2 LLM connection *shape* | Decided (`docs/DECISIONS.md`): wrap official vendor CLIs as subprocesses (`providers/cli_subprocess.py`), or auto-install for local models (`providers/local_ollama.py`) |
| 2.2 Anthropic provider | Implemented: `providers/claude_cli.py` (`ClaudeCliProvider`, wraps `claude -p`, primary path) + `providers/anthropic_api_key.py` (official `x-api-key` REST fallback) |
| 2.2 xAI/Grok provider | Implemented: `providers/xai_grok.py` (`GrokCliProvider`, wraps `grok --no-auto-update -p`) |
| 2.2 Generic OAuth device-flow provider | `providers/cloud_oauth.py` -- kept as a base for a future provider that genuinely needs its own OAuth client (none currently do; both concrete providers wrap a CLI instead) |
| 2.2 Cloud/local routing policy | **Not decided** -- "하이브리드" routing rule (when to use Claude/Grok/Ollama) doesn't exist yet |
| 2.2 LLM-based intent analysis | `llm.py:LLMBackedIntentAnalyzer` implemented against the `LLMProvider` interface. Nothing wires it into `cli.py` with a real provider yet -- `StubIntentAnalyzer` (keyword extraction, not an LLM) is still what `cli.py` uses, so `orchestrator.cli` doesn't spend real API calls |
| 2.3 Registry DB schema | Implemented (`registry/schema.sql`), matches the field list in `ROADMAP.md` 2.3 exactly |
| 2.3 Tier-1 capability-tag filter | Implemented (`registry/matcher.py`) |
| 2.3 Tier-2 embedding similarity | **Not implemented** -- no embedding model chosen yet |
| 2.3 Tier-3 LLM re-verification | **Not implemented** -- depends on the LLM decision above |
| 2.4 Execute existing app | **Stubbed** -- returns a fake result, no Phase 3 sandbox to call into yet |
| 2.5 Development planning | Implemented: `dev_agent/planning.py` (one LLM call -> work items + search keywords) |
| 2.6 Candidate search | Implemented: `dev_agent/candidates.py` -- real npm/crates.io/GitHub search APIs; PyPI via `lookup_pypi()` (name lookup, not search -- PyPI has no official search API) |
| 2.6 Candidate evaluation | Implemented: `dev_agent/evaluation.py` -- license allowlist (unknown/missing license fails closed, isn't assumed safe), maintenance thresholds, real OSV.dev vulnerability query, LLM functional-fit score |
| 2.6 Path A/B/C decision + exec_manifest | Implemented: `dev_agent/path_decision.py`, `dev_agent/codegen.py`, `dev_agent/agent.py:develop()`. Every exec_manifest this produces has `sandbox_profile_id="phase3-not-implemented"` -- code gets *generated*, never installed/run/tested |
| 2.6 "3 paths only inside Phase 3 sandbox" | **Not applicable yet** -- there's no sandbox to be inside of; `develop()` only ever generates text |
| 2.6 retry-on-test-failure | **Not implemented** -- nothing to retry against without 2.7 |
| `develop()` wired into the state machine | Implemented: `Orchestrator(dev_provider=...)` runs PLAN->DEVELOP on a registry-search miss. Path C (credentials needed) surfaces as `needs_clarification`; paths A/B raise `DevelopmentPending` (carries the `DevelopmentResult`) since there's still no 2.7/2.8 to verify/register what got generated. No `dev_provider` -> same `OrchestratorNotReady` as before |
| 2.7 테스트/검수 에이전트 | **Not implemented** |
| 2.8 앱 레지스트리 등록 | **Not implemented** |
| 2.9 Result format | Implemented (`ResultEnvelope` in `state_machine.py`) |
| Closed-loop controller / state machine | Implemented (`state_machine.py`), including retry-count and simple wall-clock timeout guards |

## Running it

```bash
cd orchestrator
python3 -m orchestrator.cli "hello demo" --seed-demo-app              # seeds a matching app first -> EXECUTE_EXISTING path
python3 -m orchestrator.cli "이미지에서 텍스트 추출해줘"                  # no matching app, no --dev-provider -> OrchestratorNotReady (expected, honest)
python3 -m orchestrator.cli "이미지에서 텍스트 추출해줘" --dev-provider claude  # runs PLAN->DEVELOP for real (needs `claude login` done)
```

`--dev-provider {claude,grok}` makes real network calls (npm/crates.io/GitHub/OSV.dev) and real LLM calls via the named CLI, so it costs actual API usage. It prints the chosen path and `exec_manifest` to stderr and exits 1 (`DevelopmentPending`) since 2.7/2.8 still don't exist to verify/register the result.

`dev_agent.agent.develop()` can also be called directly for finer control:

```python
from orchestrator.dev_agent.agent import develop
from orchestrator.providers.claude_cli import ClaudeCliProvider
from orchestrator.task_spec import TaskSpec

provider = ClaudeCliProvider()
provider.ensure_ready()  # requires `claude login` already done
result = develop(TaskSpec(raw_prompt="pdf에서 텍스트 추출", goal="extract text from a pdf"), provider)
print(result.path, result.exec_manifest)
```

## Tests

```bash
cd orchestrator
python3 -m unittest discover -s tests -v
```
