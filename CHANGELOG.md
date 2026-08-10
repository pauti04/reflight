# Changelog

All notable changes to Reflight. Format follows [Keep a Changelog](https://keepachangelog.com);
versions follow [SemVer](https://semver.org). The recording format has its own
stability contract — see [docs/format.md](docs/format.md).

## [0.1.0] — unreleased

Initial public release.

- **Record**: Anthropic + OpenAI-compatible clients, tools (`@session.tool`),
  MCP sessions, streaming; append-only `events.jsonl` (schema v1)
- **Replay**: deterministic offline re-execution with per-event hash
  verification (`ReplayDivergence` on drift); parallel tool calls matched by
  `tool_use_id`; entropy pinning (`session.pin()`) for time/random/uuid
- **Fork**: replay to seq N, go live after
- **Classify**: rule-based failure labels + LLM judge (single and ensemble);
  recurrence fingerprinting across runs
- **Test**: `reflight promote` (recorded failure → YAML regression test),
  pytest plugin, replay-first runner with live re-verification
- **Harness**: N-run executor with budget caps, reliability scoreboard,
  trends, CI gate
- **Govern**: cost/token/call budgets, loop breaker, tool-call cache;
  kills recorded in-run
- **Flight check**: opt-in detection of unrecorded network I/O during record
- **Redact**: pattern-based redaction with common PII/secret defaults
- **Interop**: OTel GenAI-convention export, LangGraph adapter, SQLite +
  Postgres stores, FastAPI server, Next.js timeline UI, static demo export
