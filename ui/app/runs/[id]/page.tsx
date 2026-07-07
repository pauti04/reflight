"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  fetchEvents,
  fetchRun,
  fmtCost,
  type AgentEvent,
  type EventRow,
  type Run,
} from "@/lib/api";

const dotColor: Record<string, string> = {
  run_start: "bg-zinc-500",
  llm_call: "bg-sky-400",
  tool_call: "bg-emerald-400",
  state_snapshot: "bg-violet-400",
  error: "bg-red-500",
  run_end: "bg-zinc-300",
};

function isFailure(event: AgentEvent): boolean {
  return (
    event.type === "error" ||
    (event.type === "tool_call" && event.is_error) ||
    (event.type === "run_end" && event.status !== "completed")
  );
}

function summarize(event: AgentEvent): string {
  switch (event.type) {
    case "run_start":
      return event.task ?? "";
    case "llm_call": {
      const blocks = event.response?.content ?? [];
      const tools = blocks
        .filter((b: AgentEvent) => b.type === "tool_use")
        .map((b: AgentEvent) => b.name);
      if (tools.length) return `→ tool_use: ${tools.join(", ")}`;
      const text = blocks.find((b: AgentEvent) => b.type === "text")?.text ?? "";
      return text.slice(0, 90);
    }
    case "tool_call":
      return `${event.name}(${JSON.stringify(event.input)})`;
    case "state_snapshot":
      return event.label ?? "";
    case "error":
      return `${event.error_type}: ${event.message}`;
    case "run_end":
      return `status=${event.status}`;
    default:
      return "";
  }
}

function Inspector({ row }: { row: EventRow }) {
  const event = row.event;
  const failure = isFailure(event);
  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-zinc-500">seq {event.seq}</span>
        <span className="font-mono font-semibold text-zinc-100">
          {event.type}
        </span>
        {failure && (
          <span className="rounded bg-red-900/60 px-2 py-0.5 text-xs font-mono text-red-300">
            ⚠ failure
          </span>
        )}
        {row.cost_usd != null && (
          <span className="font-mono text-xs text-zinc-400">
            {fmtCost(row.cost_usd)}
          </span>
        )}
      </div>

      {event.type === "llm_call" && (
        <div className="text-sm space-y-2">
          <div className="text-zinc-400 font-mono text-xs">
            {event.response?.model} · stop_reason: {event.response?.stop_reason} ·{" "}
            {event.response?.usage?.input_tokens}/
            {event.response?.usage?.output_tokens} tok
          </div>
          {(event.response?.content ?? []).map((block: AgentEvent, i: number) =>
            block.type === "text" ? (
              <p key={i} className="whitespace-pre-wrap text-zinc-200">
                {block.text}
              </p>
            ) : (
              <p key={i} className="font-mono text-emerald-300">
                {block.name}({JSON.stringify(block.input)})
              </p>
            ),
          )}
        </div>
      )}

      {event.type === "tool_call" && (
        <div className="text-sm space-y-2 font-mono">
          <p className="text-emerald-300">
            {event.name}({JSON.stringify(event.input)})
          </p>
          <p className={event.is_error ? "text-red-300" : "text-zinc-200"}>
            → {String(event.result)}
          </p>
        </div>
      )}

      <details className="text-xs">
        <summary className="cursor-pointer text-zinc-500 hover:text-zinc-300">
          raw event payload
        </summary>
        <pre className="mt-2 overflow-x-auto rounded bg-zinc-900 p-3 text-zinc-300">
          {JSON.stringify(event, null, 2)}
        </pre>
      </details>
    </div>
  );
}

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<EventRow[] | null>(null);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRun(id).then(setRun).catch((e) => setError(String(e)));
    fetchEvents(id).then(setEvents).catch((e) => setError(String(e)));
  }, [id]);

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (!events) return;
      if (e.key === "ArrowDown" || e.key === "j")
        setSelected((s) => Math.min(s + 1, events.length - 1));
      if (e.key === "ArrowUp" || e.key === "k")
        setSelected((s) => Math.max(s - 1, 0));
    },
    [events],
  );

  useEffect(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onKey]);

  if (error) return <p className="text-red-400 font-mono">{error}</p>;
  if (!run || !events) return <p className="text-zinc-500">loading…</p>;

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 className="font-mono text-lg font-semibold text-zinc-50">
          {run.run_id}
        </h1>
        <span
          className={`rounded px-2 py-0.5 text-xs font-mono ${
            run.status === "completed"
              ? "bg-emerald-900/60 text-emerald-300"
              : "bg-red-900/60 text-red-300"
          }`}
        >
          {run.status}
        </span>
        <span className="text-sm text-zinc-400">{run.task}</span>
        <span className="font-mono text-xs text-zinc-500">
          {run.model} · {run.input_tokens}/{run.output_tokens} tok ·{" "}
          {fmtCost(run.cost_usd)}
        </span>
      </div>

      {(run.findings?.length ?? 0) > 0 && (
        <div className="mb-5 rounded-lg border border-red-900/60 bg-red-950/30 p-3">
          <p className="mb-2 font-mono text-xs font-semibold text-red-300">
            ⚠ {run.findings!.length} finding{run.findings!.length > 1 ? "s" : ""}
          </p>
          <ul className="space-y-1">
            {run.findings!.map((f, i) => {
              const idx = events.findIndex((r) => r.event.seq === f.seq);
              return (
                <li key={i} className="text-sm">
                  <button
                    onClick={() => idx >= 0 && setSelected(idx)}
                    className="text-left hover:underline"
                  >
                    <span
                      className={`mr-2 rounded px-1.5 py-0.5 font-mono text-xs ${
                        f.severity === "fail"
                          ? "bg-red-900/70 text-red-200"
                          : "bg-amber-900/70 text-amber-200"
                      }`}
                    >
                      {f.label}
                    </span>
                    <span className="text-zinc-300">{f.detail}</span>
                    <span className="ml-2 font-mono text-xs text-zinc-500">
                      seq {f.seq} · conf {f.confidence.toFixed(2)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* timeline */}
        <ol className="relative space-y-1">
          {events.map((row, i) => {
            const event = row.event;
            const failure = isFailure(event);
            return (
              <li key={event.seq}>
                <button
                  onClick={() => setSelected(i)}
                  className={`flex w-full items-start gap-3 rounded-md px-3 py-2 text-left text-sm ${
                    i === selected
                      ? "bg-zinc-800/80 ring-1 ring-zinc-700"
                      : "hover:bg-zinc-900/70"
                  }`}
                >
                  <span
                    className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${
                      failure ? "bg-red-500" : dotColor[event.type] ?? "bg-zinc-500"
                    }`}
                  />
                  <span className="w-8 shrink-0 font-mono text-xs text-zinc-500">
                    {event.seq}
                  </span>
                  <span className="w-28 shrink-0 font-mono text-xs text-zinc-400">
                    {event.type}
                    {failure && <span className="ml-1 text-red-400">⚠</span>}
                  </span>
                  <span className="truncate text-zinc-300">
                    {summarize(event)}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        {/* inspector */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 lg:sticky lg:top-6 self-start">
          <Inspector row={events[selected]} />
        </div>
      </div>
      <p className="mt-4 text-xs text-zinc-600">
        ↑/↓ or j/k to step through the run
      </p>
    </div>
  );
}
