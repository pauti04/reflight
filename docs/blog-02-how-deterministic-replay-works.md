# How deterministic replay for AI agents works

*Draft — blog post #2 for the Reflight launch. Technical deep-dive.*

"Deterministic replay of a non-deterministic agent" sounds like a
contradiction. It isn't — but only if you're precise about what's actually
non-deterministic. This post is the design of Reflight's replay engine: what
gets recorded, how replay re-executes your code, why divergence is detected
rather than papered over, and where the honest limits are.

## The insight: your agent is deterministic; the world isn't

An agent loop is ordinary code. Given the same model responses and the same
tool results, it does the same thing (if you keep volatile things like
timestamps out of your prompts — more on that below). All the
non-determinism enters through two doors:

1. the LLM call — same prompt, different completion
2. tool calls — same query, different world

Close those two doors and the whole run is reproducible. So Reflight doesn't
snapshot your process, intercept syscalls, or fork VMs. It records **the
boundary**: every request that crosses from your agent to the world, and
every response that crosses back.

## Record mode: a session facade in the request path

Your agent talks to a *session* instead of a client:

```python
session = reflight.record("runs/my-run", task=task)
client = session.wrap(anthropic.Anthropic())   # every messages.create logged
tool = session.tool(tool)                       # every call logged, errors included
```

Each interaction appends one event to `runs/my-run/events.jsonl`:

```json
{"seq": 3, "type": "llm_call", "request": {…}, "request_hash": "8dece428…", "response": {…}}
{"seq": 4, "type": "tool_call", "name": "calculator", "input": {…}, "input_hash": "71ba9c5e…", "result": "18700034", "is_error": false}
```

Two details matter here:

**The request hash.** Every request is serialized to canonical JSON (sorted
keys, stable separators) and hashed. This is replay's verification key.

**Errors are data.** A tool that raises is recorded as
`result: "ZeroDivisionError: division by zero", is_error: true` — because a
recorded failure is precisely the thing you'll want to reproduce.

## Replay mode: same code, the world swapped out

```python
session = reflight.replay("runs/my-run")
client = session.wrap()            # no client, no key, no network
```

The agent code runs again — actually runs, loop and all. But `messages.create`
now: (1) pops the next recorded `llm_call`, (2) hashes the request your code
*just made*, (3) compares it to the recorded hash, and (4) deserializes the
recorded response back into a real SDK `Message` object. Tool calls do the
same with recorded results — including reconstructing the original exception
type for error results, so agent code that formats errors reproduces the
recording byte-for-byte.

Replay of a 7-event run takes ~7ms and costs $0.00, with the network
physically unavailable (our tests monkeypatch `socket.socket` to prove it).

## Divergence: the load-bearing feature

Step (3) is the part most record/replay systems skip. If your code or prompt
changed since recording, the recorded response no longer answers the request
your code is making. Serving it anyway would be a lie — the worst kind, one
that keeps your tests green while your agent rots.

Reflight raises `ReplayDivergence` at the exact seq where behavior changed.
Different consumers do different things with it:

- `verify` reports FAIL
- the test runner falls back to a **live** run and evaluates assertions there
- fork mode tells you to fork earlier

## Fork mode: replay a prefix, live from the failure

A recorded failure at seq 12 usually has 11 perfectly good events before it.
Fork mode replays the prefix and goes live at the seq you choose:

```python
session = reflight.fork("runs/failed-run", at_seq=12, client=fixed_client, tools=tools)
```

The subtle design choice: the fork **re-emits the replayed prefix into a
fresh recording**, then records the live suffix. A fork is therefore a
complete run — replayable, diffable against the original. `reflight diff`
of original vs fork shows the fix as a single highlighted divergence.

## What breaks determinism (the honest list)

- **Volatile prompt content.** `datetime.now()` in your prompt changes the
  request hash every run — replay will (correctly) diverge. Keep prompts pure,
  or expect divergence-and-live-fallback.
- **Streaming.** Chunk-level record/replay isn't built yet; buffered calls only.
- **Parallel tool calls.** We execute sequentially in block order today;
  true concurrency needs matching by tool_use_id instead of sequence.
- **SDK version drift.** Recordings store `model_dump()` output; replaying
  under a very different SDK version could change validation shape. Record the
  SDK version, warn on mismatch (planned).
- **Model-side change is invisible to replay.** Replay never consults the
  model, so a *fixed model* still replays the recorded bug. That's why the
  test runner re-verifies replay failures live before declaring them real.

## Why this composes

Once "a run" is a replayable artifact, everything downstream stops being
infrastructure and starts being a query:

- a **regression test** is a recording + assertions (replay-first, free)
- a **debugger** is a UI over the event log
- **failure classification** is pattern-matching over events
- a **consistency score** is N recordings analyzed together
- the **governor** is the same middleware path, enforcing instead of observing

That's the whole architecture: record the boundary, verify on replay, and let
everything else be a view. *(links: repo, quickstart, post #1)*
