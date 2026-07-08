# The Reflight recording format

A recording is a directory containing `events.jsonl` — one JSON object per
line, append-only, in the order things happened. This file is the entire
contract: replay, classification, diffing, promotion, the UI, and the OTel
exporter are all views over it. It is deliberately simple so other tools can
consume it — a recording is not a proprietary artifact, it's a document.

```
runs/my-run/
  events.jsonl      # the recording (source of truth)
  notes/…           # anything your tools wrote (optional)
```

## Envelope

Every event carries:

| field | type | meaning |
|---|---|---|
| `seq` | int | 0-based position, contiguous |
| `schema` | int | format version (currently `1`) |
| `ts` | float | unix seconds at emission (= call completion) |
| `type` | string | one of the six event types below |

## Event types

### `run_start`
```json
{"seq": 0, "schema": 1, "ts": 1751900000.0, "type": "run_start",
 "task": "What is the population of Tokyo…", "agent": "my-agent"}
```
`agent` is optional (set via `agent_name=`).

### `llm_call`
```json
{"seq": 1, "type": "llm_call",
 "request": { "model": "…", "messages": [...], "tools": [...] },
 "request_hash": "8dece428dd906007",
 "response": { …full provider response… },
 "provider": "openai",
 "stream": {"text_chunks": ["Tok", "yo has…"]}}
```
- `request` is the exact kwargs the agent passed; `request_hash` is
  sha256 (first 16 hex chars) of its canonical JSON (sorted keys, compact
  separators, UTF-8). Replay recomputes and compares this hash — a mismatch
  is a divergence, never silently ignored.
- `response` is the provider's response, `model_dump()`d verbatim.
- `provider` is present for OpenAI-style calls (absent = Anthropic).
- `stream` is present when the call used the streaming helper; chunks are
  replayed with the same boundaries.

### `tool_call`
```json
{"seq": 2, "type": "tool_call", "name": "calculator",
 "input": {"expression": "12 / 0"}, "input_hash": "71ba9c5e0d7ee34e",
 "tool_use_id": "toolu_001", "result": "ZeroDivisionError: division by zero",
 "is_error": true, "cached": true}
```
`tool_use_id` enables order-independent matching for parallel execution.
`cached` marks results served by the governor's cache (still recorded).

### `state_snapshot`
```json
{"seq": 3, "type": "state_snapshot", "label": "plan",
 "state": {…}, "state_hash": "…"}
```
Optional agent-state checkpoints, hash-verified on replay.

### `error`
```json
{"seq": 4, "type": "error", "error_type": "GovernorKill",
 "message": "budget exceeded: $0.5184 spent ≥ $0.50 cap"}
```
Agent crashes and governor kills. The recording captures its own
interventions.

### `run_end`
```json
{"seq": 5, "type": "run_end", "status": "completed",
 "final_text": "…", "input_tokens": 570, "output_tokens": 168}
```
`status`: `completed` | `error` | `killed` | anything your loop reports
(e.g. `max_turns_exceeded`).

## Guarantees

- **Append-only, contiguous `seq`, single `run_start` first.** Validation is
  advisory (`reflight.schema.validate_run`) — malformed recordings are
  flagged, never dropped.
- **Replayability**: the recording contains everything needed to re-execute
  the agent code that produced it with no network access. Determinism is
  hash-checked per event.
- **Stability**: `schema: 1` fields are stable; additions are
  backward-compatible extras (consumers must tolerate unknown fields).

## Consuming recordings from your own tools

Everything downstream of the recorder is ~200 lines you could rewrite in an
afternoon in another language: read JSONL, group by `type`. Examples in this
repo: the classifier (`classify.py`), the diff engine (`diff.py`), the OTel
exporter (`otel.py`), the static demo exporter. If you build a detector,
an eval, or a visualizer on top of this format, tell us — we'll link it.
