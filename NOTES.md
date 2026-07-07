# NOTES — running observations, parked ideas, honest findings

## Sprint 0 findings (2026-07-07)

### Determinism: what we proved

- Record → replay is byte-identical (event sequence, final answer, status) with
  the network **hard-blocked** (socket monkeypatched in tests, not just no key).
- A run containing a tool failure (ZeroDivisionError) replays identically —
  failures are reproducible, which is the whole point.
- Replay: ~7 ms, 0 API calls, $0.00 (recorded runs took real seconds/tokens).
- Divergence is **detected, not hidden**: changing the system prompt after
  recording makes replay raise ReplayDivergence at the first mismatched request
  (request-hash comparison), instead of silently serving stale responses.

### What breaks (or will break) determinism — the honest list

- **Streaming** — not supported yet. `messages.stream()` needs chunk-level
  recording. Deferred to Sprint 1/2; the facade makes the seam obvious.
- **Timestamps/randomness in prompts** — anything volatile the agent puts in a
  request changes its hash and (correctly) breaks replay. Mitigation later:
  canonicalization hooks or fuzzy request matching. For now: keep prompts pure.
- **Parallel tool calls** — currently executed sequentially in content-block
  order, so ordering is stable. True concurrency will need matching by
  tool_use_id instead of strict sequence. Known, not yet needed.
- **SDK version drift** — recordings store `model_dump()` output; replaying
  under a different anthropic SDK version could change validation/dump shape.
  Mitigation later: store SDK version in run_start, warn on mismatch.
- **Retries** — SDK-level automatic retries would record duplicate-ish calls.
  Not encountered yet; revisit when using the live API under load.

### Caveat

Verified with the scripted offline model (`fake_model.py`) producing real
`anthropic.types.Message` objects. The machinery is identical for the live API,
but Sprint 0 isn't formally closed until one real-API run (needs
ANTHROPIC_API_KEY) records and verifies. Confidence high; honesty higher.

### Verdict

**GO for Phase 1.** Replay determinism is real. The risky part of the whole
project works.

## Parked / deferred (with reasons)

- **Real-API verification run + judge accuracy check** — needs ANTHROPIC_API_KEY
  or an `ant auth login` profile (checked: neither present).
- **Postgres mode** — deferred pre-launch; SQLite covers the single-user local
  tool. Revisit if a hosted multi-user demo needs it.
- **OSS-agent examples gallery** — needs framework installs + live keys.
- **docker compose** — files written, unverified (docker daemon not running).
- **UI replay/fork controls** — timeline has keyboard stepping; live fork from
  the UI needs an agent-execution bridge (post-launch).

## Naming

✔ RESOLVED (2026-07-07): renamed **AgentScope → Reflight**. The original
working name collided with Alibaba's multi-agent framework. "Reflight" chosen
from a vetted shortlist: PyPI `reflight` free at decision time (register on
first publish!), no meaningful brand collisions found, aviation-native
metaphor (re-fly the flight), works as a verb. Runner-up: AgentVCR.
Recorded runs in runs/ were deliberately NOT rewritten (byte-exact replay).
