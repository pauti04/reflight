"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchCosts, fmtCost, fmtMoney } from "@/lib/api";

type Group = { key: string; runs: number; total_usd: number; mean_usd: number };
type Anomaly = {
  run_id: string;
  task: string;
  cost_usd: number;
  median_usd: number;
  factor: number;
};
type Costs = {
  total_usd: number;
  runs: number;
  per_task: Group[];
  per_agent: Group[];
  per_day: Group[];
  anomalies: Anomaly[];
};

function GroupTable({
  title,
  rows,
  sortByCost = false,
}: {
  title: string;
  rows: Group[];
  sortByCost?: boolean;
}) {
  if (!rows.length) return null;
  const ordered = sortByCost ? [...rows].sort((a, b) => b.total_usd - a.total_usd) : rows;
  const max = Math.max(...rows.map((r) => r.total_usd), 1e-9);
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <h2 className="border-b border-slate-200 bg-slate-100 px-4 py-2 font-mono text-xs font-semibold uppercase tracking-wider text-slate-500">
        {title}
      </h2>
      <ul>
        {ordered.map((row) => (
          <li
            key={row.key}
            className="border-t border-slate-200 px-4 py-2 first:border-t-0"
          >
            <div className="flex items-baseline gap-3 whitespace-nowrap">
              <span className="min-w-0 flex-1 truncate text-sm text-slate-700">{row.key}</span>
              <span className="font-mono text-xs text-slate-500">{row.runs} run{row.runs === 1 ? "" : "s"}</span>
              <span className="w-20 text-right font-mono text-sm text-slate-900">
                {fmtCost(row.total_usd)}
              </span>
            </div>
            <div className="mt-1.5 h-1 w-full overflow-hidden rounded bg-slate-200">
              <div
                className="h-full bg-indigo-500"
                style={{ width: `${Math.max((row.total_usd / max) * 100, 0.5)}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function CostsPage() {
  const [costs, setCosts] = useState<Costs | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCosts()
      .then(setCosts)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="font-mono text-red-600">{error}</p>;
  if (!costs) return <p className="text-slate-500">loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-baseline gap-6">
        <h1 className="text-lg font-semibold">Costs</h1>
        <span className="font-mono text-2xl text-slate-900">{fmtMoney(costs.total_usd)}</span>
        <span className="text-sm text-slate-500">across {costs.runs} runs</span>
      </div>
      <p className="max-w-3xl text-sm text-slate-500">
        Every AI decision costs money — each model call is billed by the token.
        This page breaks down what each agent and task actually spent, computed
        from the recordings. Replaying any of it costs nothing.
      </p>

      {costs.anomalies.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="mb-2 font-mono text-xs font-semibold text-amber-700">
            {costs.anomalies.length} cost anomal{costs.anomalies.length > 1 ? "ies" : "y"} — spend far above the task median
          </p>
          <ul className="space-y-1 text-sm">
            {costs.anomalies.map((a) => (
              <li key={a.run_id}>
                <Link
                  href={`/runs/${a.run_id}`}
                  className="font-mono text-indigo-600 hover:underline"
                >
                  {a.run_id}
                </Link>{" "}
                <span className="font-mono text-amber-700">{fmtCost(a.cost_usd)}</span>
                <span className="text-slate-600">
                  {" "}
                  — {a.factor.toFixed(1)}× the task median ({fmtCost(a.median_usd)})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <GroupTable title="per task" rows={costs.per_task} sortByCost />
        <div className="space-y-6">
          <GroupTable
            title="per agent"
            rows={costs.per_agent.filter((g) => !(g.key === "—" && costs.per_agent.length === 1))}
            sortByCost
          />
          <GroupTable title="per day" rows={costs.per_day} />
        </div>
      </div>
    </div>
  );
}
