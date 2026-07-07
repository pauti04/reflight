# Quickstart

Five minutes from clone to a timeline. No API key required — the examples use
a scripted model.

## 1. Install

```bash
git clone <repo> && cd agentscope
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
uv run agentscope import runs      # ingest into runs/agentscope.db
uv run agentscope runs             # verdicts, labels, costs
uv run agentscope show first-failure
uv run agentscope costs            # the money view
```

For the timeline UI:

```bash
uv run agentscope serve                 # API on :8724
cd ui && npm install && npm run dev     # UI on :3000
```

## 5. Instrument your own agent

```python
import agentscope, anthropic

session = agentscope.record("runs/my-run", task=task, db_path="runs/agentscope.db")
client = session.wrap(anthropic.Anthropic())   # or session.wrap_openai(OpenAI())
tool = session.tool(tool)                      # per tool function

# your agent loop, unchanged, using `client` and `tool`
session.end(final_text=answer)
```

Then everything above — replay, timeline, promote, consistency, governor —
works on your runs. Next: [concepts.md](concepts.md).
