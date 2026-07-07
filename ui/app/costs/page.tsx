"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API, fmtCost } from "@/lib/api";

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

function GroupTable({ title, rows }: { title: string; rows: Group[] }) {
  if (!rows.length) return null;
  return (
    <div className="rounded-lg border border-zinc-800">
      <h2 className="border-b border-zinc-800 bg-zinc-900 px-4 py-2 text-sm font-medium text-zinc-300">
        {title}
      </h2>
      <table className="w-full text-sm">
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-t border-zinc-800/60 first:border-t-0">
              <td className="max-w-xs truncate px-4 py-1.5 text-zinc-300">{row.key}</td>
              <td className="px-4 py-1.5 text-right text-zinc-500">{row.runs} runs</td>
              <td className="px-4 py-1.5 text-right font-mono text-zinc-200">
                {fmtCost(row.total_usd)}
              </td>
              <td className="px-4 py-1.5 text-right font-mono text-zinc-500">
                {fmtCost(row.mean_usd)} mean
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function CostsPage() {
  const [costs, setCosts] = useState<Costs | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/api/costs`, { cache: "no-store" })
      .then((r) => r.json())
      .then(setCosts)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="font-mono text-red-400">{error}</p>;
  if (!costs) return <p className="text-zinc-500">loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-baseline gap-6">
        <h1 className="text-lg font-semibold">Costs</h1>
        <span className="font-mono text-2xl text-zinc-100">{fmtCost(costs.total_usd)}</span>
        <span className="text-sm text-zinc-500">across {costs.runs} runs</span>
      </div>

      {costs.anomalies.length > 0 && (
        <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-3">
          <p className="mb-2 font-mono text-xs font-semibold text-amber-300">
            ⚠ {costs.anomalies.length} cost anomal{costs.anomalies.length > 1 ? "ies" : "y"}
          </p>
          <ul className="space-y-1 text-sm">
            {costs.anomalies.map((a) => (
              <li key={a.run_id}>
                <Link
                  href={`/runs/${a.run_id}`}
                  className="font-mono text-sky-400 hover:underline"
                >
                  {a.run_id}
                </Link>{" "}
                <span className="font-mono text-amber-200">{fmtCost(a.cost_usd)}</span>
                <span className="text-zinc-400">
                  {" "}
                  — {a.factor.toFixed(1)}× the task median ({fmtCost(a.median_usd)})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <GroupTable title="per task" rows={costs.per_task} />
        <div className="space-y-6">
          <GroupTable title="per day" rows={costs.per_day} />
          <GroupTable
            title="per agent"
            rows={costs.per_agent.filter((g) => !(g.key === "—" && costs.per_agent.length === 1))}
          />
        </div>
      </div>
    </div>
  );
}
