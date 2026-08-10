"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { fetchDiff, type AgentEvent, type Diff } from "@/lib/api";

function summarize(event: AgentEvent | undefined): string {
  if (!event) return "· (run ended)";
  switch (event.type) {
    case "run_start":
      return `run_start: ${event.task}`;
    case "llm_call": {
      const blocks = event.response?.content ?? [];
      const tools = blocks
        .filter((b: AgentEvent) => b.type === "tool_use")
        .map((b: AgentEvent) => `${b.name}(${JSON.stringify(b.input)})`);
      if (tools.length) return `llm → ${tools.join(", ")}`;
      const text = blocks.find((b: AgentEvent) => b.type === "text")?.text ?? "";
      return `llm → "${text.slice(0, 60)}"`;
    }
    case "tool_call":
      return `${event.is_error ? "ERR " : ""}${event.name}(${JSON.stringify(
        event.input,
      )}) → ${(typeof event.result === "string" ? event.result : JSON.stringify(event.result)).slice(0, 40)}`;
    case "run_end":
      return `run_end: ${event.status} — "${(event.final_text ?? "").slice(0, 50)}"`;
    default:
      return event.type;
  }
}

// tokens present in this line but not in the counterpart, via LCS — so at the
// divergence row the eye lands on exactly what changed, not a wall of sameness
// split on whitespace AND JSON punctuation so a differing value inside a
// payload highlights alone, not the whole call
const TOKEN_SPLIT = /([\s{}[\](),:]+)/;

function changedTokens(mine: string, other: string): Set<number> {
  const a = mine.split(TOKEN_SPLIT);
  const b = other.split(TOKEN_SPLIT);
  const n = a.length;
  const m = b.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  const changed = new Set<number>();
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      if (a[i].trim()) changed.add(i);
      i++;
    } else j++;
  }
  for (; i < n; i++) if (a[i].trim()) changed.add(i);
  return changed;
}

function HighlightedLine({ text, other }: { text: string; other: string }) {
  const tokens = text.split(TOKEN_SPLIT);
  const changed = changedTokens(text, other);
  return (
    <>
      {tokens.map((token, i) =>
        changed.has(i) ? (
          <mark key={i} className="rounded bg-red-500/30 px-0.5 text-red-100">
            {token}
          </mark>
        ) : (
          <span key={i}>{token}</span>
        ),
      )}
    </>
  );
}

function Column({
  title,
  events,
  divergence,
  rows,
  counterpart,
}: {
  title: string;
  events: AgentEvent[];
  divergence: number | null;
  rows: number;
  counterpart: AgentEvent[];
}) {
  return (
    <div>
      <h2 className="mb-2 font-mono text-sm text-orange-400">
        <Link href={`/runs/${title}`} className="hover:underline">
          {title}
        </Link>
      </h2>
      <ol className="space-y-1">
        {Array.from({ length: rows }, (_, i) => {
          const event = events[i];
          const state =
            divergence == null || i < divergence
              ? "same"
              : i === divergence
                ? "diverged"
                : "after";
          return (
            <li
              key={i}
              className={`rounded px-2 py-1.5 text-xs font-mono ${
                state === "diverged"
                  ? "bg-red-950/70 ring-1 ring-red-800 text-red-200"
                  : state === "after"
                    ? "bg-zinc-900/40 text-zinc-500"
                    : "bg-zinc-900/70 text-zinc-300"
              }`}
            >
              <span className="mr-2 text-zinc-600">{i}</span>
              {state === "diverged" ? (
                <HighlightedLine text={summarize(event)} other={summarize(counterpart[i])} />
              ) : (
                summarize(event)
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function DiffView() {
  const params = useSearchParams();
  const a = params.get("a") ?? "";
  const b = params.get("b") ?? "";
  const [diff, setDiff] = useState<Diff | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (a && b) fetchDiff(a, b).then(setDiff).catch((e) => setError(String(e)));
  }, [a, b]);

  if (!a || !b)
    return <p className="text-zinc-400">Pick two runs on the runs page to diff.</p>;
  if (error) return <p className="font-mono text-red-400">{error}</p>;
  if (!diff) return <p className="text-zinc-500">loading…</p>;

  const rows = Math.max(diff.a_len, diff.b_len);
  return (
    <div>
      <div className="mb-4">
        <h1 className="text-lg font-semibold">Run diff</h1>
        <p className="text-sm text-zinc-400">
          {diff.identical ? (
            "The runs are identical."
          ) : diff.divergence_seq == null ? (
            "One run is a prefix of the other — no differing event."
          ) : (
            <>
              Events 0–{diff.divergence_seq - 1} are identical; first divergence at{" "}
              <span className="font-mono text-red-300">
                seq {diff.divergence_seq}
              </span>
              .
            </>
          )}
        </p>
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Column
          title={a}
          events={diff.a}
          divergence={diff.divergence_seq}
          rows={rows}
          counterpart={diff.b}
        />
        <Column
          title={b}
          events={diff.b}
          divergence={diff.divergence_seq}
          rows={rows}
          counterpart={diff.a}
        />
      </div>
    </div>
  );
}

export default function DiffPage() {
  return (
    <Suspense fallback={<p className="text-zinc-500">loading…</p>}>
      <DiffView />
    </Suspense>
  );
}
