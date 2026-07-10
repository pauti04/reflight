# Concepts

## The event log is the product

A run is a directory with `events.jsonl`: one JSON event per line, in order —
`run_start`, `llm_call`, `tool_call`, `state_snapshot`, `error`, `run_end`.
Everything else (SQLite, UI, tests, reports) is a view over event logs. The
log is append-only and self-contained: it holds every request, every response,
every hash needed to replay.

## Sessions: one agent, four modes

Your agent talks to a **session** instead of the world — `session.messages.create(...)`,
`session.execute(...)`, or the 3-line sugar (`wrap()` / `@session.tool`). The
agent code is identical in every mode; only the session changes:

| Session | What it does |
|---|---|
| `Recorder` | pass through to the real client/tools, log everything |
| `Replayer` | serve everything from a recording; verify request hashes; never touch the network |
| `ForkSession` | replay to seq N, go live after — the fork writes a complete new recording |
| (governed `Recorder`) | same as Recorder plus budgets, loop breaker, cache |

That symmetry is the whole trick: deterministic replay is possible because
the world is injected, not reached for. Entropy the agent-loop code reaches
for directly — `time.time()`, `random`, `uuid.uuid4()` — can be injected
too: wrap the loop in `with session.pin():` and those draws are recorded and
served back identically on replay. The precise boundary of what replay
covers is mapped in [limits.md](limits.md).

## Divergence is a feature

Replay verifies at every step that the agent is making the *same* request the
recording holds (canonical-JSON hash). A mismatch raises `ReplayDivergence`.
This is not a failure of the tool — it's the honest signal that your code or
prompt changed and the recording can no longer drive it. Consumers react
differently: the test runner falls back to a live run; fork mode tells you to
fork earlier; `verify` reports FAIL.

## Failure intelligence

At ingest, rule classifiers label each run: `loop`, `wrong_tool_args`
(validated against the tool schemas the model actually saw), `tool_error_cascade`,
`crash`, `runaway`, `cost_blowout`, `governor_kill`. Verdicts: pass / warn /
fail. The optional LLM judge reads the transcript and catches what rules
can't — wrong answers, hallucinated conclusions — and merges its findings into
the stored verdict.

## Tests: replay-first economics

`reflight promote <run_id>` writes a YAML test: the recording + assertions.
The runner replays it (free). Three outcomes:

- replay **passes** → done, $0.00
- replay **diverges** → your code changed → run live, evaluate fresh
- replay **fails** → the bug reproduces against *recorded* reality, but the
  model may have changed since → re-verify live before declaring failure

Only failures and genuine changes ever spend tokens.

## Consistency over capability

`run_repeated` executes a task N times concurrently under a hard budget;
`reliability.measure` scores the fleet: pass rate, failure-mode histogram,
distinct answers, cost spread. Save a baseline, `compare()` in CI, and block
the PR when reliability drops, a new failure mode appears, or cost balloons.

## The governor

Budgets (dollars, tokens, LLM calls) enforced mid-run in the recorder's
request path; the loop circuit breaker kills N+1th identical consecutive tool
call; a cache serves repeated identical tool calls without execution (still
recorded, flagged `cached`). Kills are recorded in the run itself — error
event with the reason, status `killed`, label `governor_kill` — so the
dashboard shows the save.
