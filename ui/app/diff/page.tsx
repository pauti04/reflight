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
      return `${event.is_error ? "⚠ " : ""}${event.name}(${JSON.stringify(
        event.input,
      )}) → ${String(event.result).slice(0, 40)}`;
    case "run_end":
      return `run_end: ${event.status} — "${(event.final_text ?? "").slice(0, 50)}"`;
    default:
      return event.type;
  }
}

function Column({
  title,
  events,
  divergence,
  rows,
}: {
  title: string;
  events: AgentEvent[];
  divergence: number | null;
  rows: number;
}) {
  return (
    <div>
      <h2 className="mb-2 font-mono text-sm text-sky-400">
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
              {summarize(event)}
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
        <Column title={a} events={diff.a} divergence={diff.divergence_seq} rows={rows} />
        <Column title={b} events={diff.b} divergence={diff.divergence_seq} rows={rows} />
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
