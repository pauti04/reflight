# ⏺ Reflight

**Flight recorder for AI agents: record every run, replay it deterministically,
turn failures into regression tests.**

**▶ [Live demo](https://pauti04.github.io/reflight-demo/)** — the timeline UI
with pre-recorded runs (flaky fleet, governor kills, diffs), zero install.

Agents are programs whose most important steps are non-deterministic and
external. When one fails, the failure evaporates — re-running gives you a
*different* run. Reflight makes agent failures **reproducible**, and builds
the whole reliability loop on top:

> agent fails → the recorded run is already a reproducible test case →
> `reflight promote <run_id>` adds it to your suite → CI replays it forever,
> so that failure can never silently come back.

## What you get

| | |
|---|---|
| 🎥 **Record** | Every LLM call, tool call, token and dollar — 3 added lines |
| ⏪ **Replay** | Re-run any recording byte-identically: offline, ~7ms, $0.00 |
| 🔍 **Debug** | Timeline UI with event inspector; `--step` CLI debugger; run-diff with first-divergence highlighting |
| 🏷 **Classify** | Rule-based failure labels (loop, wrong_tool_args, cascade, crash, runaway) + optional LLM judge |
| 🔱 **Fork** | Replay to step N, go live after — test a fix mid-run |
| ✅ **Promote** | One command: recorded failure → editable YAML regression test |
| 📊 **Harness** | N-run consistency scoring, baselines, CI gate that blocks reliability regressions |
| ⛔ **Govern** | Hard cost/token budgets, loop circuit breaker, tool-call cache, cost dashboard with anomaly flags |

## Quickstart

```bash
git clone <repo> && cd reflight
uv sync                      # installs the SDK + CLI (Python 3.12+)

# record two demo runs (scripted model — no API key needed)
uv run python examples/research_agent/main.py record \
    "What is the population of Tokyo, and what is that number divided by 2?" \
    --offline --run-id demo-research
uv run python examples/research_agent/main.py record \
    "What is 12 divided by 0? Use the calculator." --offline --run-id demo-failure

# replay the failure — network off, $0.00, byte-identical
uv run python examples/research_agent/main.py replay demo-failure --step

# query them
uv run reflight import runs
uv run reflight runs
uv run reflight show demo-failure
```

### The timeline UI

```bash
uv run reflight serve            # API on :8724
cd ui && npm install && npm run dev   # UI on :3000
```

Runs list → click a run → color-coded timeline → event inspector. Findings
banner on failed runs; pick two runs to diff; `/costs` for the money view.

To build the zero-backend static demo site (what the hosted demo runs):

```bash
uv run reflight export-static        # db → ui/public/demo/*.json
cd ui && STATIC_EXPORT=1 NEXT_PUBLIC_STATIC_DEMO=1 npm run build   # → ui/out/
```

### Instrument your own agent — 3 lines

```python
import reflight

session = reflight.record("runs/my-run", task=task, db_path="runs/reflight.db")  # 1
client = session.wrap(anthropic.Anthropic())                                          # 2
my_tool = session.tool(my_tool)                        # 3 — or @session.tool

# ... your agent code runs unchanged ...
session.end(final_text=answer)
```

OpenAI-compatible clients: `client = session.wrap_openai(OpenAI())`.

Replay it later — same agent code, session swapped:

```python
session = reflight.replay("runs/my-run")     # no network, no key, no cost
client = session.wrap()
```

### Every failure becomes a regression test

```bash
uv run reflight promote my-failed-run       # → agent_tests/my-failed-run.yaml
```

Edit the assertions to state what SHOULD happen — then they're just pytest
tests. Point pytest at your agent once:

```ini
# pytest.ini
[pytest]
reflight_agent = my_pkg.agent:run_agent            # agent(session, task)
reflight_tools_factory = my_pkg.agent:make_tools   # optional
reflight_client_factory = my_pkg.agent:make_client # optional: enables live re-verify
```

and every `agent_tests/*.yaml` collects and runs in your normal `pytest`
invocation. Replay-first economics: passing tests cost $0.00; replay failures
are re-verified live; code changes trigger a live re-run. Programmatic
alternative: `reflight.testing.run_suite`. See the full loop in
[examples/flaky_agent/regression_demo.py](examples/flaky_agent/regression_demo.py)
and the CI gate in [examples/flaky_agent/ci_gate.py](examples/flaky_agent/ci_gate.py).

### The governor

```python
from reflight import Governor

session = reflight.record(..., governor=Governor(
    max_cost_usd=0.50,       # hard kill at the cap — reason recorded in the run
    loop_breaker=3,          # N identical consecutive tool calls allowed
    cache_tool_calls=True,   # serve repeats from cache (still recorded)
))
```

## Demos (all offline, no API key)

```bash
uv run python examples/quickstart/agent.py record && uv run python examples/quickstart/agent.py replay
uv run python examples/flaky_agent/fleet.py 10          # classifier labels a flaky fleet
uv run python examples/flaky_agent/fix_demo.py          # fork a failed run mid-flight
uv run python examples/flaky_agent/regression_demo.py   # fail → promote → fix → pass
uv run python examples/flaky_agent/governor_demo.py     # runaway killed at $0.50
uv run python examples/flaky_agent/ci_gate.py           # CI reliability gate (add --degrade)
```

## How replay works (and its honest limits)

Recording captures every request/response pair in an append-only
`events.jsonl`. Replay re-executes **your agent code** with all external I/O
served from the recording, verifying at each step that the code is making the
*same* requests it made before — a changed prompt or tool raises
`ReplayDivergence` instead of lying. Replay is deterministic for the recorded
path; it is **not** time travel for arbitrary changes — that's what fork mode
and live re-verification are for. Known limits (streaming, volatile prompt
content, parallel tool calls) are tracked in [NOTES.md](NOTES.md).

Verified against a real API: [examples/live_api_check.py](examples/live_api_check.py)
records two dependent live calls and replays them byte-identically with the
network blocked. Judge accuracy vs seeded ground truth: 12/12
([examples/flaky_agent/judge_accuracy.py](examples/flaky_agent/judge_accuracy.py)).

## Layout

```
sdk/reflight/    the library: recorder, replayer, fork, classify, judge,
                   testing (promote/runner), executor, reliability, governor,
                   store (SQLite), server (FastAPI), cli
ui/                Next.js timeline UI
examples/          research agent, quickstart, flaky fleet + demos
tests/             the whole story as pytest (47 tests)
docs/              quickstart, concepts, blog drafts
```

## Development

```bash
uv sync && uv run pytest       # tests
uv run ruff check .            # lint
```

Plans live in [PROJECT_PLAN.md](PROJECT_PLAN.md), [GAMEPLAN.md](GAMEPLAN.md),
[SPRINTS.md](SPRINTS.md). Apache-2.0.
