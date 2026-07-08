"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  API,
  BASE,
  STATIC,
  fetchRecurring,
  fmtCost,
  fmtTime,
  verdictStyle,
  type RecurringFailure,
} from "@/lib/api";

type TrendPoint = { bucket: string; n: number; passes: number; pass_rate: number };

type TaskReport = {
  task: string;
  runs: number;
  passes: number;
  pass_rate: number;
  verdicts: Record<string, number>;
  failure_histogram: Record<string, number>;
  distinct_answers: number;
  cost_mean: number | null;
  total_cost: number;
  trend?: TrendPoint[];
};

function Bar({ value, className }: { value: number; className: string }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-zinc-800">
      <div className={`h-full ${className}`} style={{ width: `${value * 100}%` }} />
    </div>
  );
}

export default function ReliabilityPage() {
  const [reports, setReports] = useState<TaskReport[] | null>(null);
  const [recurring, setRecurring] = useState<RecurringFailure[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const url = STATIC ? `${BASE}/demo/reliability.json` : `${API}/api/reliability`;
    fetch(url, { cache: "no-store" })
      .then((r) => r.json())
      .then(setReports)
      .catch((e) => setError(String(e)));
    fetchRecurring().then(setRecurring).catch(() => setRecurring([]));
  }, []);

  if (error) return <p className="font-mono text-red-400">{error}</p>;
  if (!reports) return <p className="text-zinc-500">loading…</p>;
  if (reports.length === 0)
    return <p className="text-zinc-400">No runs to score yet.</p>;

  const maxHist = Math.max(
    1,
    ...reports.flatMap((r) => Object.values(r.failure_histogram)),
  );

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">
        Reliability <span className="text-zinc-500">— consistency by task</span>
      </h1>

      {recurring.length > 0 && (
        <div className="rounded-lg border border-orange-900/50 bg-orange-950/15 p-4">
          <p className="mb-3 font-mono text-xs font-semibold uppercase tracking-wider text-orange-300">
            ↻ recurring failures — the same bug, again and again
          </p>
          <ul className="space-y-2">
            {recurring.map((bug) => (
              <li key={bug.signature} className="text-sm">
                <span className="mr-2 rounded bg-red-900/70 px-1.5 py-0.5 font-mono text-xs text-red-200">
                  {bug.label} ×{bug.count}
                </span>
                <span className="text-zinc-300">{bug.detail}</span>
                <span className="ml-2 font-mono text-xs text-zinc-500">
                  first {fmtTime(bug.first_seen)} ·{" "}
                  {bug.run_ids.slice(0, 5).map((id, i) => (
                    <span key={id}>
                      {i > 0 && ", "}
                      <Link href={`/runs/${id}`} className="text-orange-400 hover:underline">
                        {id}
                      </Link>
                    </span>
                  ))}
                  {bug.run_ids.length > 5 && ` +${bug.run_ids.length - 5}`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {reports.map((report) => (
        <div key={report.task} className="rounded-lg border border-zinc-800 p-4">
          <div className="mb-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="max-w-xl truncate text-sm text-zinc-200">{report.task}</span>
            <span className="font-mono text-xs text-zinc-500">
              {report.runs} runs · {report.distinct_answers} distinct answer
              {report.distinct_answers === 1 ? "" : "s"} ·{" "}
              {report.cost_mean != null ? `${fmtCost(report.cost_mean)} mean` : "unpriced"} ·{" "}
              {fmtCost(report.total_cost)} total
            </span>
          </div>

          <div className="mb-1 flex items-center gap-3">
            <span className="w-24 shrink-0 text-right font-mono text-2xl text-zinc-100">
              {Math.round(report.pass_rate * 100)}%
            </span>
            <div className="grow">
              <Bar
                value={report.pass_rate}
                className={
                  report.pass_rate >= 0.9
                    ? "bg-emerald-500"
                    : report.pass_rate >= 0.5
                      ? "bg-amber-500"
                      : "bg-red-500"
                }
              />
              <div className="mt-1 flex gap-2">
                {Object.entries(report.verdicts).map(([verdict, n]) => (
                  <span
                    key={verdict}
                    className={`rounded px-1.5 py-0.5 font-mono text-xs ${
                      verdictStyle[verdict] ?? "bg-zinc-800 text-zinc-400"
                    }`}
                  >
                    {verdict} {n}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {(report.trend?.length ?? 0) > 1 && (
            <div className="mt-3 flex items-end gap-1">
              <span className="mr-2 font-mono text-xs text-zinc-600">trend</span>
              {report.trend!.map((point) => (
                <div key={point.bucket} className="group relative">
                  <div
                    className={`w-8 rounded-sm ${
                      point.pass_rate >= 0.9
                        ? "bg-emerald-600"
                        : point.pass_rate >= 0.5
                          ? "bg-amber-600"
                          : "bg-red-700"
                    }`}
                    style={{ height: `${8 + point.pass_rate * 28}px` }}
                  />
                  <span
                    className="pointer-events-none absolute -top-7 left-1/2 hidden -translate-x-1/2
                               whitespace-nowrap rounded bg-zinc-800 px-1.5 py-0.5 font-mono
                               text-xs text-zinc-200 group-hover:block"
                  >
                    {point.bucket}: {Math.round(point.pass_rate * 100)}% of {point.n}
                  </span>
                </div>
              ))}
            </div>
          )}

          {Object.keys(report.failure_histogram).length > 0 && (
            <div className="mt-3 space-y-1">
              {Object.entries(report.failure_histogram).map(([label, count]) => (
                <div key={label} className="flex items-center gap-3">
                  <span className="w-40 shrink-0 truncate text-right font-mono text-xs text-red-300">
                    {label}
                  </span>
                  <div className="grow">
                    <Bar value={count / maxHist} className="bg-red-900" />
                  </div>
                  <span className="w-6 font-mono text-xs text-zinc-500">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
