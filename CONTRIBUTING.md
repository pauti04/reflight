# Contributing to Reflight

Thanks for looking under the hood. This project is young; issues and small
PRs are the most useful thing you can send.

## The one rule that makes bug reports great

**Attach a recording.** Reflight bugs almost always reproduce from the
`events.jsonl` of the run that misbehaved — that's the whole point of the
tool. Redact anything sensitive first:

```python
session = reflight.record(run_dir, redact=reflight.redact_common())
```

If the recording itself can't be shared, `reflight show <run_id>` output or
the failing test's divergence message is the next best thing.

## Dev setup

```bash
git clone https://github.com/pauti04/reflight && cd reflight
uv sync
uv run pytest            # 90+ tests, a few skip without Postgres
uv run ruff check .
```

The UI lives in `ui/` (Next.js): `cd ui && npm install && npm run dev`.
Postgres-only tests run in CI's service container; locally they skip unless
`REFLIGHT_PG_DSN` is set.

## What we'll happily merge

- Bug fixes with a regression test (a recorded run in `tests/` fixtures is
  ideal — promote it!)
- Adapters for agent frameworks (see `sdk/reflight/adapters/langchain.py`
  for the pattern: inject the wrapped client, don't fork the framework)
- Consumers of the recording format (detectors, exporters, visualizers) —
  see [docs/format.md](docs/format.md); we link external ones from the README
- Docs that make the honest-limits map ([docs/limits.md](docs/limits.md))
  more honest

## What to open an issue for first

- New event types or changes to the recording format (schema stability
  matters more than any feature)
- Anything that would make replay less strict — divergence-instead-of-lying
  is the product

## Style

`ruff` is the law (`uv run ruff check .`). Match the docstring voice of the
module you're editing. Tests tell stories — a test that records, breaks
something, and replays beats three unit tests.
