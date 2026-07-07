# Reflight — portfolio page draft

*Copy for the portfolio site entry. Structure: problem → demo → architecture →
what I learned. Swap in real links + screenshots at publish time.*

---

## Reflight

**Flight recorder for AI agents — record every run, replay it
deterministically, turn failures into regression tests.**
Python · FastAPI · SQLite · Next.js · Anthropic + OpenAI SDKs · Apache-2.0

### The problem

Agent failures don't reproduce. The model answers differently every run, so
the 2am loop that burned $40 and told a user "the answer is 42" is gone by
the time you read the logs. Teams ship agents with no regression tests for
exactly the failures they've already seen — the tooling to write one doesn't
exist. (Agent observability was widely called the biggest unsolved problem in
the 2026 agent-engineering surveys.)

### What it does

- **Record** every LLM call and tool call with 3 added lines (Anthropic +
  OpenAI-compatible clients)
- **Replay** any run byte-identically: offline, milliseconds, $0.00 — with
  divergence *detection* when the code changed, never silent staleness
- **Debug** in a timeline UI: color-coded events, failure findings, run-diff
  with first-divergence highlighting, fork-from-step-N
- **Promote** any failed run to an editable YAML regression test in one
  command; replay-first runner (passing tests are free; failures re-verify live)
- **Score reliability** over N runs (pass rate, failure-mode histogram, answer
  stability) and **gate CI** on a checked-in baseline
- **Govern cost**: hard budgets and a loop circuit-breaker that kill runaway
  runs — with the kill recorded in the run itself

### The demo (60 seconds)

1. A flaky agent runs 10× → dashboard: 4 pass / 6 fail, every failure
   auto-labeled (`loop`, `wrong_tool_args`, `tool_error_cascade`)
2. Diff a pass vs a fail → identical until seq 1, where the failing run sent
   `{"q": …}` instead of `{"query": …}` — highlighted in red
3. `reflight promote nightly-run` → test fails while the bug exists (via free
   replay) → fix the agent → test passes (live re-verify)
4. A runaway agent gets killed at a $0.50 budget; the cost dashboard flags it
   at 173× the task median

### Architecture notes

Session-facade design: the agent talks to a session, not the world, so
record/replay/fork are the same code path with the world swapped out.
Canonical-JSON request hashing makes divergence detectable at the exact event.
Event logs (JSONL) are the source of truth; SQLite is a query index;
classification and cost are computed at ingest. ~50 pytest tests tell the
whole story, including network-blocked replay proofs.

### Lineage

Successor to **ChainCheck** (agent hallucination circuit breaker): ChainCheck
proved you can intercept a misbehaving agent in real time; Reflight grows that
instinct into the full loop — record, replay, test, govern.

### What I learned

- Deterministic replay is a *boundary-recording* problem, not a
  snapshot problem — and honesty about divergence is the load-bearing feature
- Replay can't see model-side fixes (it never consults the model); the test
  runner's replay-first / re-verify-live economics fell out of that constraint
- A fork that re-emits its replayed prefix becomes a complete, diffable run —
  small design choice, outsized payoff
