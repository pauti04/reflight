# What replay can and can't see

Reflight's replay guarantee is precise, and it's worth being precise about
its edges. This page is the honest map: read it before trusting a green
replay, and before filing a bug about a divergence that is actually your
agent being nondeterministic.

## The guarantee

Replay re-executes **your agent code** with every external exchange served
from the recording. At each step the replayer hash-verifies that the agent
is making the *same* request it made live — same prompt, same tools, same
arguments. If the code drifted, you get `ReplayDivergence` with the exact
seq where it happened, never a silently wrong result.

So: **replay proves your orchestration logic is deterministic given the
recorded world.** That's the property that makes recorded failures
reproducible and promoted tests meaningful at $0.00.

## What's covered

| source of behavior | covered? | how |
|---|---|---|
| LLM responses (Anthropic, OpenAI-style) | yes | served verbatim from the recording |
| Streaming responses | yes | same chunk boundaries |
| Tool results (session tools, `@session.tool`, MCP) | yes | served verbatim; errors re-raised as the original type |
| Parallel tool calls | yes | matched by `tool_use_id`, order-independent |
| Agent state you snapshot | yes | hash-verified at each `state_snapshot` |
| `time.time` / `time.time_ns` in agent-loop code | with `session.pin()` | per-call capture, served back in order |
| `random.*` in agent-loop code | with `session.pin()` | PRNG re-seeded with the recorded seed |
| `uuid.uuid4` in agent-loop code | with `session.pin()` | per-call capture |

## What's not covered

Be suspicious of anything that touches the world without going through the
session. These will not diverge loudly — they simply happen again on replay:

- **Unwrapped side effects.** A `requests.get()` call, a file write, a
  subprocess — if it doesn't go through `session.execute`, a wrapped client,
  or a decorated tool, replay re-executes it for real. The fix is structural:
  route external I/O through tools. That's good agent hygiene anyway.
- **`datetime.datetime.now()`.** It's a C-level attribute and can't be
  patched; the pin covers `time.time()` / `time.time_ns()` — use those in
  pinned code (or read the clock inside a tool, where the result is recorded).
- **The global PRNG inside tool bodies.** The pin seeds the *global*
  `random` instance. Tool bodies execute only during record, so a tool that
  draws from the global PRNG shifts later agent-loop draws relative to
  replay. Give tools their own `random.Random()` instance.
- **Environment drift your code reads directly** — env vars, config files,
  `os.cpu_count()`. Same rule: read it through a tool or snapshot it.

## Two asymmetries worth understanding

**Model-side fixes are invisible to replay.** Replay never consults the
model, so if a failure was the model's (not your code's) and you changed the
prompt, replay of the *old* recording still shows the old behavior — by
design; a recording is evidence, not a prediction. This is why the test
runner re-verifies replay failures live (`mode: replay→live`) before calling
a regression real.

**Code fixes are loud.** Change your orchestration logic and replay
diverges at the first request that differs, telling you exactly where the
new behavior departs from the recording — which is what `reflight fork`
is for: replay the prefix, go live at the divergence.

## Practical rule of thumb

If a green replay surprises you, ask: *did every input to my decision logic
come through the session?* When the answer is yes, replay is proof. When
it's no, the gap is one of the bullets above — and the fix is to move that
input behind a tool, a snapshot, or the pin.
