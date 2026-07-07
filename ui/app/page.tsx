"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API, fetchRuns, fmtCost, fmtTime, type Run } from "@/lib/api";

const statusColor: Record<string, string> = {
  completed: "bg-emerald-900/60 text-emerald-300",
  error: "bg-red-900/60 text-red-300",
  max_turns_exceeded: "bg-amber-900/60 text-amber-300",
};

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRuns().then(setRuns).catch((e) => setError(String(e)));
  }, []);

  if (error)
    return (
      <div className="text-zinc-400">
        <p className="text-red-400 font-mono mb-2">cannot reach the API</p>
        <p>
          Start it with <code className="text-zinc-200">agentscope serve</code>{" "}
          (expected at <code className="text-zinc-200">{API}</code>)
        </p>
      </div>
    );
  if (!runs) return <p className="text-zinc-500">loading…</p>;
  if (runs.length === 0)
    return (
      <p className="text-zinc-400">
        No runs recorded yet — record one, then{" "}
        <code className="text-zinc-200">agentscope import</code>.
      </p>
    );

  return (
    <div>
      <h1 className="text-lg font-semibold mb-4">
        Recorded runs <span className="text-zinc-500">({runs.length})</span>
      </h1>
      <div className="overflow-x-auto rounded-lg border border-zinc-800">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900 text-zinc-400 text-left">
            <tr>
              <th className="px-4 py-2 font-medium">run</th>
              <th className="px-4 py-2 font-medium">status</th>
              <th className="px-4 py-2 font-medium">task</th>
              <th className="px-4 py-2 font-medium">model</th>
              <th className="px-4 py-2 font-medium text-right">events</th>
              <th className="px-4 py-2 font-medium text-right">tokens</th>
              <th className="px-4 py-2 font-medium text-right">cost</th>
              <th className="px-4 py-2 font-medium">recorded</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr
                key={run.run_id}
                className="border-t border-zinc-800/70 hover:bg-zinc-900/60"
              >
                <td className="px-4 py-2 font-mono">
                  <Link
                    href={`/runs/${run.run_id}`}
                    className="text-sky-400 hover:underline"
                  >
                    {run.run_id}
                  </Link>
                </td>
                <td className="px-4 py-2 whitespace-nowrap">
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-mono ${
                      statusColor[run.status ?? ""] ?? "bg-zinc-800 text-zinc-300"
                    }`}
                  >
                    {run.status}
                  </span>
                  {run.tool_errors > 0 && (
                    <span className="ml-2 text-xs text-red-400 font-mono">
                      ⚠ {run.tool_errors}
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 max-w-md truncate text-zinc-300">
                  {run.task}
                </td>
                <td className="px-4 py-2 font-mono text-zinc-400">
                  {run.model ?? "?"}
                </td>
                <td className="px-4 py-2 text-right text-zinc-400">
                  {run.event_count}
                </td>
                <td className="px-4 py-2 text-right font-mono text-zinc-400">
                  {run.input_tokens ?? 0}/{run.output_tokens ?? 0}
                </td>
                <td className="px-4 py-2 text-right font-mono text-zinc-300">
                  {fmtCost(run.cost_usd)}
                </td>
                <td className="px-4 py-2 text-zinc-500 text-xs whitespace-nowrap">
                  {fmtTime(run.started_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
