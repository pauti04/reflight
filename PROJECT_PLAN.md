# AgentScope — Flight Recorder, Reliability Harness & Cost Governor for AI Agents

*(working name — alternatives: BlackBox, Replay, TraceKit)*

## One-liner

An open-source toolkit that makes AI agent failures reproducible: record every run
like a flight recorder, replay it deterministically to debug it, and turn it into a
regression test — with reliability scoring and cost governance built on the same
trace layer.

## The killer loop

**Every failure becomes a regression test.**

> Agent fails → the recorded run is already a reproducible test case → one command
> adds it to the suite → CI replays it forever, so that failure can never silently
> come back.

The three pillars below all ship, but this loop is the center of gravity and the
demo. Positioning: a **debugger + test generator for agents** (think pytest + VCR),
not another observability platform competing with LangSmith/Langfuse on breadth.
Replay honesty: replay is deterministic for the *recorded path* (exactly what
debugging and regression tests need); it is not time travel for arbitrary prompt
changes — fork mode (replay to step N, then go live) is the answer for testing fixes.

## Why this project (2026 demand signals)

- Agentic AI job postings grew ~280% YoY; agent developers earn a 15–20% salary premium.
- Agent observability/debugging is widely called the biggest unsolved problem in the
  space: agents are non-deterministic, so failures can't be snapshotted and replayed.
- Eval tooling is fragmented with no consensus on what "good" looks like; reliability
  (consistency across runs) has barely improved despite 24 months of model releases.
- Cost control is a top-5 production scaling challenge ($0.15/run workflows blow up at volume).
- Hiring managers reward production instincts — evals, error handling, deployment,
  live demos — over "yet another chatbot" portfolios.

## The three pillars, one foundation

```
                    ┌─────────────────────────────────────────┐
                    │              Trace Layer                │
                    │  SDK captures: LLM calls, tool calls,   │
                    │  state changes, tokens, latency, errors │
                    └───────┬───────────┬───────────┬─────────┘
                            │           │           │
                  ┌─────────▼──┐  ┌─────▼──────┐  ┌─▼───────────┐
                  │  Flight    │  │ Reliability │  │    Cost     │
                  │  Recorder  │  │  Harness    │  │  Governor   │
                  │ replay +   │  │ N-run       │  │ budgets,    │
                  │ timeline   │  │ consistency │  │ loop kill,  │
                  │ debugger   │  │ scoring, CI │  │ dashboards  │
                  └────────────┘  └────────────┘  └─────────────┘
```

Everything is a **trace event**. Capture once, use three ways.

## Architecture

### 1. Instrumentation SDK (Python first, TS later)
- Thin wrapper / middleware around LLM clients (Anthropic SDK first, then
  OpenAI-compatible) and tool executors.
- Emits structured events: `llm_call`, `tool_call`, `state_snapshot`, `error`,
  `run_start/end` — each with inputs, outputs, token counts, latency, cost.
- OpenTelemetry-compatible span model (GenAI semantic conventions) so it plugs into
  existing observability stacks — this is a big adoption + credibility win.
- Integration adapters: raw SDK, LangGraph, Claude Agent SDK, MCP servers.

### 2. Trace store + API
- Backend: FastAPI + Postgres (JSONB for event payloads); SQLite mode for local dev
  so `pip install && run` works with zero setup.
- Ingest endpoint (batched, async), query API (runs, events, diffs, aggregates).

### 3. Deterministic replay engine (the hard, impressive part)
- **Record mode**: persist every external interaction (LLM responses, tool results).
- **Replay mode**: re-run the agent with all external I/O served from the recording —
  fully deterministic, free, offline. Enables step-through debugging and "what changed"
  diffs between two runs of the same task.
- **Fork mode**: replay up to step N, then go live from there (test a fix mid-run).

### 4. Failure classifier
- Rule-based first, LLM-judge second. Auto-tag failed runs with the known taxonomy:
  - wrong tool arguments / wrong tool order
  - lost or corrupted multi-turn state
  - reasoning/tool loops (repeated near-identical calls)
  - context problems (truncation, bad retrieval)
  - cost blowout / timeout

### 5. Reliability harness (pillar 2)
- Define tasks in YAML/Python: input, success criteria (assertions + LLM judge).
- Run each task N times live; score **consistency** (pass rate, variance, cost spread),
  not just one-shot accuracy.
- Baseline + regression detection: diff pass rates across model/prompt/code versions.
- CI integration: GitHub Action that fails the build on reliability regressions.

### 6. Cost governor (pillar 3)
- Sits in the same middleware path as the recorder.
- Per-run and per-agent token/dollar budgets with hard enforcement (raise/kill).
- Loop detection → circuit breaker (natural ChainCheck lineage).
- Cache layer for repeated identical tool calls.
- Cost-per-task dashboards and anomaly alerts.

### 7. Web UI
- Next.js + Tailwind. Timeline view of a run (the "flight recorder" visual — this is
  the demo centerpiece), event inspector, run diff view, reliability scoreboard,
  cost dashboard.

## Stack

| Layer | Choice | Why |
|---|---|---|
| SDK | Python (+ TS later) | Where agent dev happens |
| Backend | FastAPI + Postgres/SQLite | Async ingest, JSONB, zero-setup local mode |
| UI | Next.js + Tailwind | Fast to polish, great for demos |
| Tracing model | OpenTelemetry GenAI conventions | Interop + industry credibility |
| Eval judge | Claude (Sonnet for judging) | Cheap, good enough for judging |
| Packaging | pip + docker compose | `docker compose up` demo in 60s |

## Phases (~4 months part-time)

### Phase 0 — Spike (week 1)
Prove the core trick: record and deterministically replay one nontrivial agent
(e.g. a small research agent with 3 tools). No UI, no DB — JSON files. If replay
works, everything else is engineering.

### Phase 1 — Flight Recorder MVP (weeks 2–5)
SDK event capture → SQLite store → minimal timeline UI → replay CLI.
**Milestone: record a real agent run, watch it in the timeline, replay it step-by-step.**

### Phase 2 — Failure intelligence (weeks 6–8)
Failure classifier (rules + LLM judge), run-diff view, fork-mode replay.
**Milestone: point it at a deliberately flaky agent; it names the failure mode.**

### Phase 3 — Reliability harness (weeks 9–12)
Task definitions, N-run executor, consistency scoring, regression diffs, GitHub Action.
**Milestone: CI fails a PR that degrades agent reliability. Blog post #1.**

### Phase 4 — Cost governor (weeks 13–15)
Budgets, loop circuit breaker, tool-call cache, cost dashboard.
**Milestone: runaway-loop agent gets killed at budget; dashboard shows the save.**

### Phase 5 — Polish & launch (weeks 16+)
Postgres mode, docker compose, docs site, 3-min demo video, example gallery
(instrument 2–3 popular open-source agents), Show HN / r/LocalLLaMA launch.

## Portfolio strategy

- **Live demo > repo**: hosted demo with a pre-recorded flaky agent people can replay
  in the browser without installing anything.
- **The money shot**: side-by-side diff of two runs of the same task — one passed,
  one failed — with the classifier explaining why. No other portfolio has this.
- Write-ups per phase: "How deterministic replay for agents works" is a
  blog post that hiring managers in this space will actually read.
- ChainCheck lineage: position the loop circuit breaker as ChainCheck v2 —
  continuity looks great in a portfolio narrative.

## Risks & mitigations

- **Replay determinism is hard** (streaming, parallel tool calls, timestamps) →
  Phase 0 spike de-risks it before any real investment; start with sequential agents.
- **Scope creep across 3 pillars** → pillars ship in strict order; each phase ends
  in a demoable milestone, so the project is portfolio-ready from week 5 onward.
- **Crowded observability market** (LangSmith, Langfuse, Braintrust) → differentiate
  on *deterministic replay + fork mode + consistency scoring*, which the incumbents
  are weakest at; OTel compatibility means "works alongside," not "replaces."
