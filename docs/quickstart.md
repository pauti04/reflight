# Quickstart

Five minutes from clone to a timeline. No API key required — the examples use
a scripted model.

## 1. Install

```bash
git clone <repo> && cd reflight
uv sync              # Python 3.12+; uv manages the toolchain
```

## 2. Record a run

```bash
uv run python examples/research_agent/main.py record \
    "What is 12 divided by 0? Use the calculator." --offline --run-id first-failure
```

This runs a small research agent (hand-written loop, three tools) against a
scripted model and records every LLM call and tool call to
`runs/first-failure/events.jsonl`. The divide-by-zero is deliberate — you just
recorded a reproducible failure.

## 3. Replay it

```bash
uv run python examples/research_agent/main.py replay first-failure --step
```

Same agent code, but every response is served from the recording: no network,
no key, milliseconds, $0.00. `--step` pauses at each event like a debugger.
`verify` asserts the replay is byte-identical:

```bash
uv run python examples/research_agent/main.py verify first-failure
```

## 4. Query and browse

```bash
uv run reflight import runs      # ingest into runs/reflight.db
uv run reflight runs             # verdicts, labels, costs
uv run reflight show first-failure
uv run reflight costs            # the money view
```

For the timeline UI:

```bash
uv run reflight serve                 # API on :8724
cd ui && npm install && npm run dev     # UI on :3000
```

## 5. Instrument your own agent

```python
import reflight, anthropic

session = reflight.record("runs/my-run", task=task, db_path="runs/reflight.db")
client = session.wrap(anthropic.Anthropic())   # or session.wrap_openai(OpenAI())
tool = session.tool(tool)                      # per tool function

# your agent loop, unchanged, using `client` and `tool`
session.end(final_text=answer)
```

Then everything above — replay, timeline, promote, consistency, governor —
works on your runs. Next: [concepts.md](concepts.md).
