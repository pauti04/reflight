# Launch post drafts

## Show HN

**Title:** Show HN: Reflight – record AI agent runs, replay them deterministically, turn failures into regression tests

**Body:**

Agent failures don't reproduce: the model answers differently every run, so
the 2am loop that invented an answer is gone by the time you read the logs.
That means nobody writes regression tests for the agent failures they've
already seen — the repro doesn't exist.

Reflight is an open-source flight recorder for agents. Wrap your LLM client
and tools (3 added lines, Anthropic or OpenAI-compatible), and every run
becomes an append-only event log you can:

- **replay deterministically** — your actual agent code re-executes with all
  external I/O served from the recording: offline, ~ms, $0.00. Replay verifies
  request hashes at every step, so a changed prompt raises a divergence error
  instead of lying.
- **debug** — timeline UI, failure auto-labeling (loops, wrong tool args,
  cascades), diff two runs with the first divergence highlighted, fork a run
  mid-flight to test a fix.
- **promote to a test** — `reflight promote <run_id>` writes an editable YAML
  regression test. Replay-first economics: passing tests cost $0.00; replay
  failures get re-verified live (a recording pins stale model behavior, so a
  model-side fix never shows up in replay — took us a while to get this
  semantic honest).
- **gate CI on reliability** — run a task N times under a cost cap, score
  consistency (pass rate, failure-mode histogram, answer stability), and fail
  the PR against a checked-in baseline.
- **govern cost** — hard budgets and a loop circuit breaker that kill runaway
  runs, with the kill recorded in the run itself.

Everything in the repo runs offline against a scripted model — no API key
needed to try the demos. Apache-2.0. Feedback very welcome, especially on the
replay-divergence semantics and what would make you trust promoted tests.

https://github.com/pauti04/reflight — hosted demo: https://pauti04.github.io/reflight-demo/

---

## X/Twitter thread

1/ Your AI agent failed at 2am. This morning the failure is gone — the model
answers differently every run. You can't reproduce it, so you can't test for
it, so it ships again. We built a flight recorder to fix this. 🧵

2/ Reflight records every LLM call + tool call (3 added lines). The recording
is enough to re-run your *actual agent code* deterministically: offline,
milliseconds, $0.00. Failures replay as the same failure, every time.

3/ Replay is honest: it hashes every request your code makes and compares
against the recording. Changed your prompt? ReplayDivergence at the exact
step — never a stale green test.

4/ The killer loop: `reflight promote <run_id>` turns any recorded failure
into a regression test. Fails (free, via replay) while the bug exists. Passes
when it's fixed. CI replays it forever.

5/ Plus: timeline debugger, failure auto-labeling, run-diffing with
first-divergence highlighting, fork-a-run-mid-flight, N-run consistency
scoring with CI gates, and hard cost budgets with a loop circuit breaker.

6/ A runaway agent with no turn limit, killed at a $0.50 budget — reason
recorded in the run, dashboard flags it at 173× the task median. The flight
recorder captures its own intervention.

7/ Open source, Apache-2.0, all demos run offline without an API key.
https://github.com/pauti04/reflight — hosted demo: https://pauti04.github.io/reflight-demo/ — would love eyes on the replay semantics.

---

## r/LocalLLaMA

**Title:** Reflight: open-source flight recorder for AI agents — deterministic replay, failure→test promotion, CI reliability gates (all demos run offline)

Body: condensed Show HN body + note that recording works with any
OpenAI-compatible endpoint (so local models via llama.cpp/ollama/vllm servers
work), and replay needs no model at all — nice for debugging local-model
agents without burning GPU time.
