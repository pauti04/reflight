# Reflight — 3-minute demo video script

*Shot-by-shot. Every command below actually works offline in the repo today —
record the terminal at 100×30, UI at 1400×900. Practice run ≈ 2:40.*

---

**[0:00–0:15] Cold open — the problem** *(voiceover over a static slide or the
timeline UI showing a failed run)*

> "Last night your agent got stuck in a loop and told a user the answer was
> 42. Try to debug it this morning and the failure is gone — the model answers
> differently every run. Agent failures don't reproduce. Reflight fixes that."

**[0:15–0:45] Record & replay** *(terminal)*

```bash
uv run python examples/research_agent/main.py record \
    "What is 12 divided by 0? Use the calculator." --offline --run-id crash
uv run python examples/research_agent/main.py replay crash --step
```

> "Reflight wraps your agent's LLM client and tools — three added lines — and
> records every call. Now replay it: same code, every response served from the
> recording. No network, milliseconds, zero dollars. Step through it like a
> debugger — there's the divide-by-zero, frozen in time."

*(Hit Enter through the 3 steps; linger on the ⚠ ERROR line.)*

**[0:45–1:15] The timeline UI + the fleet** *(browser)*

```bash
uv run python examples/flaky_agent/fleet.py 10
```

*(Switch to UI runs list.)*

> "Run a flaky agent ten times: four pass, six fail — and every failure is
> auto-labeled. Loops. Wrong tool arguments. Error cascades. Click one —"

*(Open flaky-01: findings banner → timeline → inspector.)*

> "— and there's the loop on the timeline: the same calculator call five times,
> then a made-up answer."

**[1:15–1:40] The diff — the money shot** *(UI /diff)*

*(Pick flaky-00 vs flaky-02 → diff page.)*

> "Diff a passing run against a failing one. Identical at step zero…
> divergence at step one, highlighted: the good run sent `query`, the bad run
> sent `q`. That's the bug, on one screen."

**[1:40–2:20] Every failure becomes a regression test** *(terminal)*

```bash
uv run python examples/flaky_agent/regression_demo.py
```

> "Here's the loop that changes how you ship agents. The agent fails. One
> command — `reflight promote` — turns that recorded failure into a test. The
> test fails while the bug exists, via free offline replay. Fix the agent…
> and it passes. Wire it into CI and reliability becomes a number your pull
> requests can't shrink: this gate just blocked a PR that dropped the pass
> rate from 40 to 30 percent."

*(Optionally flash `ci_gate.py --degrade` output on the last sentence.)*

**[2:20–2:45] The governor** *(terminal)*

```bash
uv run python examples/flaky_agent/governor_demo.py
```

> "And for the failures you don't catch: hard budgets. A runaway agent, no
> turn limit — killed at fifty cents, the reason recorded in the run itself.
> The cost dashboard flags it at 173 times the task median."

**[2:45–3:00] Close** *(README or repo page)*

> "Record with three lines. Replay anything. Promote failures to tests. Gate
> CI on reliability. Reflight — flight recorder for AI agents. Link below."

---

*Production notes: dark terminal theme matching the UI (zinc-950); mouse off
screen during typing; pre-warm all commands so nothing stalls; keep the cursor
on the red divergence row during the 1:15 beat.*
