# ARCHIVED — not part of the Grok Bot OS image

This tree is historical. Nothing in `Containerfile`, `build_files/build.sh`,
or the boot session imports or starts it. See [`../README.md`](../README.md)
and `docs/DECISIONS.md` (2026-10-18 pivot). The notes below describe the
old AI-OS orchestrator as it existed when it was archived.

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
| Phase 4 connection logic (`onboarding.py`) | Implemented: provider picker (Claude/Grok/Ollama/custom CLI), `connect_claude_via_browser()`/`connect_grok()` try each CLI's real login subcommand first (`claude auth login` / `grok login` -- note `claude auth login`, not `claude login`, which doesn't exist; a real bug, 2026-07-11) (spawns a real browser via the OS's baked-in Firefox), fall back to token paste (`authenticate_with_token`) only if that fails; saved connection persisted to `~/.config/oais/provider.json`. Shared unchanged by both UIs below |
| Phase 4 window management (`webshell/wm.py`) | Implemented: closes whatever new Firefox window a login flow opens (via sway IPC, `swaymsg -t get_tree` diffed before/after) once that flow's subprocess exits -- fixes a real "logged in successfully but stuck on the OAuth success page with no way back to the shell" bug (this kiosk has no window chrome/title bar). First version (2026-07-11) alone wasn't enough: the kiosk's own desktop is itself a Firefox `--kiosk` window, so a bare `firefox <url>` from a login flow likely just remoted into that *same* running instance as a new tab instead of opening a separate window for `wm.py` to find -- diagnosed 2026-07-13 from a screenshot showing the bug persisting after the first fix (`docs/DECISIONS.md`). Fixed with `system_files/usr/local/bin/oais-open-browser` (`firefox --new-window`, registered as the default `xdg-open`/`$BROWSER` target in `build_files/build.sh`) so login popups always get their own con_id. Best-effort/no-op if swaymsg or a sway IPC socket isn't available (tests, `onboarding_cli.py`'s headless path). Also added real `Mod1+Tab`/`Mod1+Shift+Tab` focus-cycling keybindings (`system_files/etc/sway/config`) as a general fallback so a human can move between open windows even if `wm.py` doesn't catch one |
| Phase 4 GUI boot shell (`webshell/`, `webshell_cli.py`) | **What sway actually boots into now.** A local stdlib `http.server` (`webshell/server.py`) serves a single-page UI (`webshell/static/`, styled after Claude Design's prompt screen) that Firefox displays via `--kiosk`: a centered prompt card, then a scrollable tile grid below it (built-in commands + installed apps). **Single unified pipeline**: every tile click and every hand-typed prompt both POST to the one `/api/prompt` endpoint -- there's no separate per-icon API. `/api/connect`/`/api/connect-token` were removed entirely |
| Phase 4 slash-command router (`webshell/commands.py`) | Implemented: `/llm [id]` (list/connect providers, incl. `/llm custom <cli> [login_command...]`), `/token claude <token>` (browser-login fallback), `/system` / `/system network` (real `nmcli device status` call) / `/system info` (`/etc/os-release` + `platform.uname()`), `/cli` (spawns a real `foot` terminal window via `subprocess.Popen`), `/help`. `api.py:prompt_payload()` routes any `/`-prefixed text here; everything else goes to the real `Orchestrator`. Connecting still runs on a background thread (`webshell/connect.py`) against a thread-safe `ConnectionState` (`webshell/state.py`) so `/api/status` polling keeps working during a real browser OAuth flow -- unchanged from before, just called directly instead of through a second REST endpoint. **Not implemented**: actually changing network configuration (`/system network` is read-only status) |
| Phase 4 headless fallback (`onboarding_cli.py`) | Implemented: the original plain-text prompt loop (predates the slash-command router, doesn't use it), kept for SSH/recovery-console use where there's no display for Firefox to render into. Same underlying connection logic (`onboarding.py`) as the GUI shell above |
| Phase 4 live log panel (`webshell/logbuf.py`) | Implemented: thread-safe `LogBuffer` ring buffer; `GET /api/logs?after=<id>` long-polls it (blocks up to 20s for new entries) so the UI's right-side log panel updates without a websocket. Every layer that shells out to a real CLI accepts an optional `log` callable, threaded from `server.py` all the way down through `commands.py`/`connect.py`/`onboarding.py` to `providers/cli_subprocess.py` and `providers/local_ollama.py`, which log real install/login/pull progress and exit codes -- not synthetic status text |
| Phase 4 OS image integration (`Containerfile`, `build_files/build.sh`, `system_files/etc/sway/`, `system_files/usr/local/bin/oais-shell-launch`) | Implemented: `sway`+`foot`+`firefox`+`google-noto-sans-cjk-ttc-fonts` installed via `dnf5` (the CJK font was added after a real boot showed Korean text rendering as tofu boxes), orchestrator package copied to `/usr/lib/oais/orchestrator` (not `/opt` -- see `docs/DECISIONS.md` on `/var` persistence), `aios` user's login shell execs `sway` on tty1 (autologin via a systemd getty override), which execs `webshell_cli` -> Firefox `--kiosk` fullscreen. **Boot itself was verified once** (autologin -> sway -> a shell rendered, confirmed via a real UTM screenshot) but that was against the old text-shell version; this GUI-shell version and the font fix are unverified -- needs a rebuild + reboot test |

## Running it

```bash
cd orchestrator
python3 -m orchestrator.cli "hello demo" --seed-demo-app              # seeds a matching app first -> EXECUTE_EXISTING path
python3 -m orchestrator.cli "이미지에서 텍스트 추출해줘"                  # no matching app, no --dev-provider -> OrchestratorNotReady (expected, honest)
python3 -m orchestrator.cli "이미지에서 텍스트 추출해줘" --dev-provider claude  # runs PLAN->DEVELOP for real (needs `claude auth login` done)
```

`--dev-provider {claude,grok}` makes real network calls (npm/crates.io/GitHub/OSV.dev) and real LLM calls via the named CLI, so it costs actual API usage. It prints the chosen path and `exec_manifest` to stderr and exits 1 (`DevelopmentPending`) since 2.7/2.8 still don't exist to verify/register the result.

`dev_agent.agent.develop()` can also be called directly for finer control:

```python
from orchestrator.dev_agent.agent import develop
from orchestrator.providers.claude_cli import ClaudeCliProvider
from orchestrator.task_spec import TaskSpec

provider = ClaudeCliProvider()
provider.ensure_ready()  # requires `claude auth login` already done
result = develop(TaskSpec(raw_prompt="pdf에서 텍스트 추출", goal="extract text from a pdf"), provider)
print(result.path, result.exec_manifest)
```

## Tests

```bash
cd legacy/orchestrator
python3 -m unittest discover -s tests -v
```
