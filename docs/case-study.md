# Case study: fifteen green runs booked a meeting on a Sunday

*Everything below actually happened, against a live API, on 2026-07-10. The
recordings are committed under [`runs/sched-*`](../runs) — you can replay
every run in this document yourself, offline, with
`reflight show sched-000` or the hosted demo. The script is
[`examples/scheduler_live/case_study.py`](../examples/scheduler_live/case_study.py).*

## The setup

A scheduling agent (`gpt-4o-mini`, OpenAI function calling) with three
tools — `get_today`, `check_availability`, `book_meeting` — and one honest
task:

> Book a 45-minute design sync **next Wednesday at 3:30pm**. If that slot
> conflicts with an existing meeting, book the next conflict-free 45-minute
> slot that same afternoon (between 13:00 and 18:00).

The calendar fixture anchors "today" at **Friday 2026-07-10**, so next
Wednesday is **2026-07-15** — where 15:00–16:00 and 16:30–17:15 are busy.
The requested 15:30 conflicts; the only correct answer is **17:15**.

We ran it five times through Reflight's N-run executor with a $0.50 budget
cap. Then, because the result was hard to believe, ten more across two
further batches. Total spend for all fifteen live runs: **under a cent**.

## What happened

**Fifteen out of fifteen runs booked 2026-07-12 — a Sunday — at 15:30, and
confirmed it to the user as "Wednesday, July 12th."**

The recorded transcript makes the failure exact. The agent *did* call
`get_today` first, *did* receive `{"date": "2026-07-10", "weekday":
"Friday"}` — and then computed "next Wednesday" as July 12 anyway
(2026-07-12 is the coming *Sunday*; Wednesday is the 15th):

```
TOOL get_today {} -> {"date": "2026-07-10", "weekday": "Friday"}
TOOL check_availability {date: 2026-07-12, start: 15:30} -> available (empty day)
TOOL book_meeting {date: 2026-07-12, start: 15:30} -> booked, EVT-2026-07-12-1530
LLM  "The design sync has been successfully booked for Wednesday, July 12th at 15:30."
```

And here is the uncomfortable part: **every tool-level check passed.** The
wrong day has an empty calendar, so `check_availability` said yes,
`book_meeting` succeeded, no tool errored, no loop, no crash. Reflight's
rule classifiers — correctly — found nothing. Fifteen green verdicts.
Reliability report: 100% pass, **one distinct answer**. The agent isn't
flaky. It is *consistently, confidently wrong*, which no amount of
retry-and-compare can surface.

## What caught it

Two layers, both part of Reflight, both run on the recordings after the
fact — no re-execution, no additional agent spend:

1. **The LLM judge** (`judge_run`, here gpt-4o-mini judging itself) read
   the transcripts and flagged runs `judge_wrong_answer` at 0.90 confidence
   — e.g. *"the agent incorrectly stated the date of the meeting as
   Wednesday, July 12, 2026, when it is actually a Sunday."* But across the
   three batches the same judge caught **5 of 5, then 3 of 5, then 1 of 5**
   identical failures. A judge is a probabilistic net — cheap and useful,
   and exactly as nondeterministic as the agents it judges. Measuring that
   variance took thirty seconds precisely because the runs were recordings:
   re-judging is free re-reading, not re-running.

2. **A deterministic assertion** — fifteen lines that read each recording
   and check the booked slot against ground truth — caught **every run in
   every batch**, and `store.add_finding` folded the verdicts to `fail`
   with a shared signature, so the scoreboard shows the recurrence:
   `wrong_slot ×5`, same bug, every run.

That layering is the point of an open recording format: the judge and the
assertion are both just *consumers of the same events.jsonl*. Encode ground
truth once and every future recording — CI runs included — gets checked
against it for $0.00.

## Why this needed a flight recorder

- **The failure would otherwise be a support ticket.** "Agent booked the
  wrong day" from a user, days later, with nothing to inspect. Here it's
  five committed recordings; `reflight show sched-000` puts the exact
  moment on screen, and replay reproduces it offline, byte-identical (we
  verified with the network hard-blocked).
- **Pass rates lied; the recording didn't.** Every metric short of reading
  the transcript said this agent works. The transcript is the only place
  the bug exists — which is an argument for keeping every transcript.
- **Recurrence turned five anecdotes into one bug.** The shared fingerprint
  groups all five runs under a single finding — this is one defect, not
  five incidents.

## Footnote: what dogfooding caught in Reflight itself

Running this study also surfaced two real gaps in Reflight, both fixed in
the same commit: the pricing table had no OpenAI models, and cost
computation didn't read OpenAI's `prompt_tokens`/`completion_tokens` usage
keys — so the first batch of live runs ingested at $0.0000. A case study
that finds bugs in the microscope too is a good day.
