# AgentScope — Sprint Plan

2-week sprints, ~16 focused hours each (per the ~8 hrs/week cadence in
[GAMEPLAN.md](GAMEPLAN.md)). Every sprint ends with a **demo artifact** — a runnable
command or a screen recording. A sprint without a demo artifact is not done.

**Sprint ritual** (30 min, end of each sprint): check off what shipped, record the
demo, write 3 lines in `NOTES.md` (what worked / what surprised / what's at risk),
adjust the next sprint's scope. If a sprint slips, cut its stretch items — never
its definition of done.

---

## Sprint 0 — Replay Spike ★ (Week 1, one week only)

**Goal:** prove deterministic replay is real before investing anything else.

- [x] Example research agent: hand-written loop, Claude + 3 tools (search stub, calculator, save_note)
- [x] `recorder.py`: every LLM/tool request+response → `runs/<id>/events.jsonl`
- [x] `replayer.py`: re-run agent with all external I/O served from the recording
- [x] `--step` mode: pause per event, print payload
- [x] `NOTES.md`: what breaks determinism (streaming? parallel tools? timestamps?)
- [ ] Formal close-out: one run recorded against the **real API** verifies (needs ANTHROPIC_API_KEY)

**Done when:** a recorded run — including a *failed* one — replays byte-identical
with networking off, in <2s, at $0.00.
**Demo artifact:** terminal recording of record → unplug → replay.
**Kill/pivot check:** infeasible after ~10 hrs → pivot core to trace inspection, reassess.

---

## Sprint 1 — Real SDK + Storage (Weeks 2–3)

**Goal:** from spike scripts to an installable SDK someone else could use.

- [x] Monorepo scaffold: `uv`, ruff, pytest, CI on push; Apache-2.0
- [x] Event schema v1 (typed + versioned): `run_start`, `llm_call`, `tool_call`, `state_snapshot`, `error`, `run_end`
- [x] Auto-instrumentation: wrap the Anthropic client — **≤3 lines to instrument an existing agent**
- [x] SQLite store; token + dollar cost computed per event at ingest
- [x] `agentscope runs` / `agentscope show <run_id>` CLI
- [x] Unit tests for recorder/replayer against schema v1

**Done when:** a fresh agent project can `pip install`, add 3 lines, and get recorded runs in SQLite.
**Demo artifact:** the 3-line instrumentation diff + CLI output.

## Sprint 2 — Timeline UI + Replay Debugger (Weeks 4–5)

**Goal:** the flight-recorder experience. End of Phase 1.

- [x] FastAPI query endpoints (runs list, run detail, event payloads) — `agentscope serve`
- [x] Next.js UI: runs list → run timeline → event inspector (prompt/response/tool args/cost)
- [x] Replay step-through wired into the UI (keyboard ↑/↓ stepper; live fork/replay from UI comes with Phase 2 fork mode) — CLI `replay --step` remains
- [x] Failed events visually flagged on the timeline

**Done when:** you can watch any recorded run like a video and inspect every step.
**Demo artifact:** 🎬 **Milestone demo #1** — instrument in 3 lines, run, watch, replay a failure.

## Sprint 3 — Failure Classification (Weeks 6–7)

**Goal:** the tool names *why* runs failed.

- [x] Rule classifiers: loop (repeated near-identical calls), wrong tool args (schema validation), token/cost blowout, tool-error cascade (+ crash, runaway)
- [x] Failure tags + confidence surfaced in timeline UI and CLI
- [x] Run-diff view: two runs of one task side-by-side, first divergence highlighted (`agentscope diff` + /diff page)
- [x] Flaky example agent with 3 seeded failure modes (becomes the eternal demo fixture)

**Done when:** 10 runs of the flaky agent → dashboard shows pass/fail with each failure auto-labeled correctly.
**Demo artifact:** screenshot of the labeled failure dashboard + diff view.

## Sprint 4 — LLM Judge + Fork Mode (Week 8, one week)

**Goal:** finish Phase 2's fuzzy half.

- [x] LLM-judge classifier for failures rules can't catch (bad reasoning, wrong answer) — `agentscope judge`, injectable client
- [x] Fork mode: replay to step N, go live from there (test a fix mid-run) — forks are complete runs, diffable vs the original
- [ ] Judge accuracy sanity check against ~20 hand-labeled runs (needs real API credentials — parked with the Sprint 0 close-out)

**Done when:** a hallucination-style failure gets a sensible judge label; a fix can be tested via fork without re-running from scratch.
**Demo artifact:** 🎬 **Milestone demo #2** — failure labeled, forked, fixed.

## Sprint 5 — Promote + Test Runner (Weeks 9–10)

**Goal:** the killer feature. Failures become regression tests.

- [x] **`agentscope promote <run_id>`** — converts a recorded run into a replayable test case with auto-generated assertions (editable)
- [x] Task spec format: input, assertions, optional LLM-judge rubric (YAML, commented)
- [x] Test runner: replay-mode execution of promoted tests (fast, free, offline; replay failures re-verified live so model-side fixes are caught)
- [x] N-run live executor with concurrency + hard cost cap

**Done when:** a failed run is promoted in one command and the resulting test fails until the agent is fixed, then passes.
**Demo artifact:** terminal recording of fail → promote → fix → pass.

## Sprint 6 — Consistency Scoring + CI (Weeks 11–12)

**Goal:** the reliability harness, complete. End of Phase 3.

- [x] Consistency report: pass rate, variance, cost spread, failure-mode histogram over N runs
- [x] Baselines + regression diff across model/prompt/code versions (tolerances for pass-rate wobble + cost growth)
- [x] GitHub Action: run promoted tests + N-run suite, fail PR on regression, readable report via GITHUB_STEP_SUMMARY (PR checks page)
- [x] Blog post #1 draft: "Your agent's failures should be regression tests" (docs/)

**Done when:** a PR that subtly degrades the flaky agent is blocked by CI with a report a stranger can read.
**Demo artifact:** 🎬 **Milestone demo #3** — the blocked PR.

## Sprint 7 — Cost Governor (Weeks 13–14)

**Goal:** budgets and the ChainCheck-v2 circuit breaker.

- [x] Per-run / per-agent budgets (tokens + dollars + llm-call count), hard enforcement with recorded kill reason (error event + status "killed" + governor_kill label)
- [x] Loop circuit breaker (detection already exists from Sprint 3 — now it *acts*)
- [x] Identical-tool-call cache with hit-rate stats (cached calls still recorded, flagged `cached`)
- [x] Cost dashboard: per task / per agent / per day, anomaly flags (`agentscope costs`, /api/costs, /costs page)

**Done when:** a runaway agent is killed at a $0.50 budget and the dashboard shows the save.
**Demo artifact:** 🎬 **Milestone demo #4** — the kill, on the timeline.

## Sprint 8 — Production Polish (Weeks 15–16)

**Goal:** strangers can run it in 60 seconds.

- [ ] Postgres mode + `docker compose up` one-liner
- [ ] Docs site: quickstart, concepts, API reference, the 4 demo recordings
- [ ] Instrument 2–3 popular OSS agents → `examples/` gallery
- [ ] OpenAI-compatible client support (opens the addressable audience)

**Done when:** a friend follows the quickstart cold and gets a timeline in <5 minutes.
**Demo artifact:** the friend test, honestly reported.

## Sprint 9 — Launch (Weeks 17–18)

**Goal:** ship it to the world; harvest the portfolio assets.

- [ ] Hosted read-only demo: pre-recorded flaky-agent runs, replayable in the browser, zero install
- [ ] 3-minute demo video (the money shot: side-by-side pass/fail diff + promote-to-test)
- [ ] Blog post #2: "How deterministic replay for AI agents works"
- [ ] Show HN + r/LocalLLaMA + X thread; respond to feedback for a week
- [ ] Portfolio page: problem → demo → architecture → what I learned

**Done when:** launched, and the portfolio page exists.
**Demo artifact:** the launch itself.

---

## Deliberately NOT doing (backlog, revisit post-launch)

- TypeScript SDK · LangGraph/CrewAI adapters · multi-tenant hosted SaaS ·
  OTel exporter (schema stays OTel-*compatible* from Sprint 1) · agent fleet
  dashboard ("Agent Ops control room") · distributed replay

## Progress tracker

| Sprint | Weeks | Theme | Status |
|---|---|---|---|
| 0 ★ | 1 | Replay spike | ☐ |
| 1 | 2–3 | SDK + storage | ☐ |
| 2 | 4–5 | Timeline UI 🎬 | ☐ |
| 3 | 6–7 | Failure classification | ☐ |
| 4 | 8 | Judge + fork 🎬 | ☐ |
| 5 | 9–10 | Promote + test runner | ☐ |
| 6 | 11–12 | Consistency + CI 🎬 | ☐ |
| 7 | 13–14 | Cost governor 🎬 | ☐ |
| 8 | 15–16 | Polish | ☐ |
| 9 | 17–18 | Launch 🚀 | ☐ |
