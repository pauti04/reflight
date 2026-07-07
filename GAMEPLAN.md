# AgentScope — Game Plan

Companion to [PROJECT_PLAN.md](PROJECT_PLAN.md) (*what and why*) and
[SPRINTS.md](SPRINTS.md) (*the sprint-by-sprint execution schedule — the doc to
open every work session*). Check things off as you go.

## Locked decisions (revisit only with good reason)

| Decision | Choice |
|---|---|
| Language | Python 3.12+, `uv` for packaging |
| First LLM provider | Anthropic SDK (add OpenAI-compatible in Phase 1) |
| Storage | JSON files (Phase 0) → SQLite (Phase 1) → Postgres (Phase 5) |
| UI | None until Phase 1; then Next.js + Tailwind |
| Trace format | Custom events now, mapped to OTel GenAI conventions in Phase 1 |
| License | Apache-2.0 |
| Repo | Single monorepo: `sdk/`, `server/`, `ui/`, `examples/` |
| Cadence | ~8 hrs/week; one milestone demo at the end of every phase |

## Operating rules

1. **Never skip ahead.** Cost governor ideas go in `NOTES.md`, not in Phase 0 code.
2. **Every phase ends with something demoable** — a runnable command or a screen
   recording. If it can't be demoed, the phase isn't done.
3. **Write the blog post outline the same week a phase ships**, while it's fresh.
4. **Weekly checkpoint** (15 min): what shipped, what's blocked, is the phase still
   on schedule? If a phase slips >2 weeks, cut scope, not quality.

---

## Phase 0 — The Replay Spike (Week 1) ← YOU ARE HERE

**Question to answer:** can we record an agent run and replay it *byte-for-byte
deterministically* with zero API calls?

### Build

- [ ] `examples/research_agent/` — a small deliberately-imperfect agent:
      Claude + 3 tools (web_search stub, calculator, save_note), agent loop
      written by hand (no framework — we need to own the loop to instrument it)
- [ ] `sdk/recorder.py` — wraps the Anthropic client + tool dispatcher; writes
      every request/response pair to `runs/<run_id>/events.jsonl`
- [ ] `sdk/replayer.py` — same agent code, but the wrapper serves LLM responses
      and tool results FROM the recording instead of calling out
- [ ] `replay --step` CLI flag — pause at each event, print prompt/response/tool
      call, wait for Enter (the primitive timeline debugger)

### Success criteria (all must hold)

- [ ] Replay of a recorded run produces the identical final answer and identical
      event sequence, with the network disconnected
- [ ] Replay costs $0.00 and finishes in <2 seconds
- [ ] A run that *failed* (agent used wrong tool args) replays identically —
      failures are reproducible, which is the whole point
- [ ] Honest answer written down in `NOTES.md`: what breaks determinism?
      (streaming? temperature? parallel tools? timestamps in prompts?)

### Kill / pivot criterion

If after ~10 focused hours deterministic replay looks fundamentally infeasible
(not just hard), we don't abandon — we pivot the core to **trace inspection
without replay** (still valuable, weaker demo) and reassess.

---

## Phase 1 — Flight Recorder MVP (Weeks 2–5)

- [ ] Event schema v1 (typed, versioned): `run_start`, `llm_call`, `tool_call`,
      `state_snapshot`, `error`, `run_end`
- [ ] SQLite store + FastAPI ingest/query endpoints
- [ ] Auto-instrumentation: monkeypatch/wrap Anthropic client so users add
      **≤3 lines** to instrument an existing agent
- [ ] Timeline UI: list runs → click run → vertical timeline of events →
      click event → full payload inspector
- [ ] Token + cost per event and per run, computed at ingest
- [ ] **Milestone demo:** screen recording — instrument the example agent in 3
      lines, run it, watch the timeline, replay a failed run step-by-step

## Phase 2 — Failure Intelligence (Weeks 6–8)

- [ ] Rule-based classifiers: repeated near-identical tool calls (loop),
      tool-schema validation failures (wrong args), token blowout
- [ ] LLM-judge classifier for the fuzzy cases; classifier confidence shown in UI
- [ ] Run-diff view: two runs of the same task side-by-side, first divergence highlighted
- [ ] Fork-mode replay: replay to step N, go live after
- [ ] **Milestone demo:** flaky agent runs 10×; dashboard shows 7 pass / 3 fail
      with each failure auto-labeled; diff view explains the divergence

## Phase 3 — Reliability Harness (Weeks 9–12)

- [ ] **`agentscope promote <run_id>` — one command turns any recorded failed run
      into a replayable regression test.** This is the killer feature; build it first.
- [ ] Task spec format: input, assertions, optional LLM-judge rubric
- [ ] N-run executor with concurrency + cost cap
- [ ] Consistency report: pass rate, variance, cost spread, failure-mode histogram
- [ ] Baselines + regression diff across model/prompt/code versions
- [ ] GitHub Action: fail PR on reliability regression
- [ ] **Milestone demo + blog post #1:** a PR that subtly degrades the agent gets
      blocked by CI with a readable report

## Phase 4 — Cost Governor (Weeks 13–15)

- [ ] Per-run/per-agent budgets (tokens + dollars), hard enforcement
- [ ] Loop circuit breaker (ChainCheck v2) — kills runs, records why
- [ ] Identical-tool-call cache
- [ ] Cost dashboard: per task, per agent, per day; anomaly flags
- [ ] **Milestone demo:** runaway agent killed at $0.50 budget; dashboard shows it

## Phase 5 — Polish & Launch (Weeks 16+)

- [ ] Postgres mode, docker compose one-liner, docs site
- [ ] Instrument 2–3 popular OSS agents for an examples gallery
- [ ] Hosted read-only demo with pre-recorded runs (no install needed)
- [ ] 3-minute demo video; Show HN + r/LocalLLaMA launch
- [ ] Blog post #2: "How deterministic replay for AI agents works"

---

## Immediate next actions

1. Scaffold repo (`uv init`, monorepo layout, ruff + pytest, git init)
2. Build the example research agent (bare loop, 3 tools)
3. Build `recorder.py` → record 5 runs including at least 1 failure
4. Build `replayer.py` → chase determinism until success criteria pass
5. Write `NOTES.md` findings → decide Phase 1 go/no-go
