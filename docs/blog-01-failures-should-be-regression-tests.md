# Your agent's failures should be regression tests

*Draft — blog post #1 for the Reflight launch.*

At 2am your agent got stuck in a loop, called the same tool eleven times, and
confidently told a user the answer was 42. By the time you look at the logs,
the failure has evaporated: re-running the agent gives you a different run,
because the model answers differently and the APIs return different data. You
are debugging fog.

Ordinary software solved this decades ago. A bug report comes with a repro;
the repro becomes a regression test; CI makes sure the bug never returns
silently. Agents broke that loop at the first step — **you can't reproduce a
nondeterministic failure** — so nobody writes the regression test, and the
same failure modes keep shipping.

The fix is to stop treating the failure as an event and start treating it as
**data you already captured**.

## Record everything, replay anything

Reflight wraps your agent's LLM client and tools (three added lines) and
records every request/response pair to an append-only event log. That log is
enough to *re-execute your agent code deterministically*: replay serves every
model response and tool result from the recording, byte-for-byte, offline, in
milliseconds, for $0.00. Failures included — a recorded loop replays as the
same loop, every time. The fog becomes a video you can scrub.

(Replay is honest about its limits: it verifies at each step that your agent
is making the *same* requests it made during recording. If your code or
prompt changed, it raises a divergence error instead of lying.)

## One command: failure → test

```
$ reflight promote nightly-run
promoted nightly-run → agent_tests/nightly-run.yaml
```

The promoted test contains the recording plus auto-generated assertions:
"status must be completed", "no classifier findings", "never produce the
recorded-bad answer again". You edit in what *should* happen:

```yaml
assertions:
  - type: no_findings
  - type: final_text_not_equals
    value: "I seem to be stuck. The answer is 42."
  - type: final_text_contains        # ← the line you add
    value: "18,700,034"
```

## The economics: replay first, live only when it matters

The runner replays each test against its recording. Three things can happen:

- **Replay passes** → test passes, $0.00. Your unchanged agent still behaves.
- **Replay diverges** → your code or prompt changed. The runner re-runs the
  test live and evaluates the assertions against fresh reality.
- **Replay fails** → the bug reproduces against *recorded* reality — but the
  recording pins old model behavior, and a model-side fix would never show up
  in replay. So failures are **re-verified live** before being declared real.

Passing tests are free. Only failures and genuine changes spend tokens. A
test promoted from a failure keeps failing while the bug exists and passes
once the agent — code or model — is actually fixed.

## Close the loop in CI

One run tells you an agent *can* do a task. N runs tell you whether it
*reliably does* — and reliability, not capability, is what's been flat across
two years of model releases. Reflight's executor runs a task N times
concurrently under a hard cost cap and scores consistency:

```
pass rate:     40%  (4 pass, 6 not)
answers:       3 distinct
failure modes:
  wrong_tool_args        ██████ 6
  loop                   ███ 3
  tool_error_cascade     ███ 3
```

Check a baseline into the repo, and the gate fails the PR when the pass rate
drops, a new failure mode appears, or cost balloons:

```
✗ gate FAILED:
  · promoted regression suite failed: ['classifier findings: loop', ...]
  · pass rate dropped 40% → 30%
```

That's the whole idea: **every production failure becomes a regression test,
and reliability becomes a number your CI refuses to let shrink.**

## Try it

Reflight is open source (Apache-2.0): record with 3 lines, replay any run
step-by-step in a timeline UI, promote failures with one command, gate CI on
consistency. *(links, install, demo video)*

---
*Notes for final edit: add real install instructions once published; link the
timeline-UI screenshots and the fork-mode post (#2).*
