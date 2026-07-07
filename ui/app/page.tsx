"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  API,
  fetchRuns,
  fmtCost,
  fmtTime,
  parseLabels,
  verdictStyle,
  type Run,
} from "@/lib/api";

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const router = useRouter();

  useEffect(() => {
    fetchRuns().then(setRuns).catch((e) => setError(String(e)));
  }, []);

  const toggle = (id: string) =>
    setPicked((p) =>
      p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id],
    );

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
      <div className="mb-4 flex items-center gap-4">
        <h1 className="text-lg font-semibold">
          Recorded runs <span className="text-zinc-500">({runs.length})</span>
        </h1>
        <button
          disabled={picked.length !== 2}
          onClick={() => router.push(`/diff?a=${picked[0]}&b=${picked[1]}`)}
          className="rounded border border-zinc-700 px-3 py-1 text-xs font-mono
                     text-zinc-300 enabled:hover:bg-zinc-800 disabled:opacity-40"
        >
          diff {picked.length}/2 selected
        </button>
      </div>
      <div className="overflow-x-auto rounded-lg border border-zinc-800">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900 text-zinc-400 text-left">
            <tr>
              <th className="px-3 py-2"></th>
              <th className="px-4 py-2 font-medium">run</th>
              <th className="px-4 py-2 font-medium">verdict</th>
              <th className="px-4 py-2 font-medium">failure labels</th>
              <th className="px-4 py-2 font-medium">task</th>
              <th className="px-4 py-2 font-medium text-right">events</th>
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
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={picked.includes(run.run_id)}
                    onChange={() => toggle(run.run_id)}
                    className="accent-sky-500"
                  />
                </td>
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
                      verdictStyle[run.verdict ?? ""] ?? "bg-zinc-800 text-zinc-300"
                    }`}
                  >
                    {run.verdict ?? "?"}
                  </span>
                </td>
                <td className="px-4 py-2">
                  <div className="flex flex-wrap gap-1">
                    {parseLabels(run.labels).map((label) => (
                      <span
                        key={label}
                        className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs font-mono text-red-300"
                      >
                        {label}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-2 max-w-sm truncate text-zinc-300">
                  {run.task}
                </td>
                <td className="px-4 py-2 text-right text-zinc-400">
                  {run.event_count}
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
