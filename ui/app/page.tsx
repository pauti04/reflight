"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import FdrPanel from "@/components/fdr-panel";
import LoopTabs from "@/components/loop-tabs";
import {
  API,
  STATIC,
  fetchRuns,
  fmtCost,
  fmtMoney,
  fmtTime,
  parseLabels,
  verdictStyle,
  type Run,
} from "@/lib/api";

type VerdictFilter = "all" | "pass" | "warn" | "fail";

const BUG_TRAIL = [
  { href: "/reliability", label: "3 agents, 19 runs", sub: "the scoreboard" },
  {
    href: "/runs/refund-01",
    label: "the refund API rejects every call",
    sub: "amount sent as a string",
  },
  {
    href: "/diff?a=refund-00&b=refund-01",
    label: "the diff shows why",
    sub: '49.99 vs "$49.99"',
  },
  {
    href: "/runs/refund-runaway",
    label: "runaway killed at $2.00",
    sub: "gateway never settles",
  },
];

function Landing() {
  if (!STATIC) return null;
  return (
    <div className="gridbg -mx-6 mb-10 px-6">
      <div className="grid grid-cols-1 items-center gap-8 py-8 lg:grid-cols-2">
        <div>
          <h1 className="text-3xl font-bold leading-tight text-slate-50">
            Your agent failed at 2 a.m.
            <br />
            <span className="text-cyan-400">By morning, the failure was gone.</span>
          </h1>
          <p className="mt-4 text-slate-400">
            Reflight records every run an agent makes, replays any of them
            deterministically, and turns the failures into regression tests.
            The panel on the right is a{" "}
            <span className="text-slate-200">real recording, replaying now</span>:
            a support agent processing a damage claim sends the refund amount as
            a string, and retries the same broken call until it gives up.
            Caught, labeled, reproducible. Nothing here is mocked.
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            <Link
              href="/runs/refund-01"
              className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950
                         transition-colors hover:bg-cyan-400"
            >
              Step through this failure
            </Link>
            <Link
              href="/diff?a=refund-00&b=refund-01"
              className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200
                         transition-colors hover:border-cyan-700 hover:text-cyan-200"
            >
              Spot a bug in one diff
            </Link>
          </div>
        </div>
        <FdrPanel />
      </div>

      <LoopTabs />

      <div className="mt-6 rounded-lg border border-slate-800 bg-slate-900/30 p-4">
        <p className="mb-3 font-mono text-xs font-semibold uppercase tracking-wider text-slate-500">
          follow one bug through the system
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {BUG_TRAIL.map((stop, i) => (
            <span key={stop.href} className="flex items-center gap-2">
              <Link
                href={stop.href}
                className="group rounded-md border border-slate-800 bg-slate-950 px-3 py-2
                           transition-colors hover:border-cyan-800"
              >
                <span className="block text-sm text-slate-200 group-hover:text-cyan-200">
                  {stop.label}
                </span>
                <span className="block font-mono text-xs text-slate-600">{stop.sub}</span>
              </Link>
              {i < BUG_TRAIL.length - 1 && <span className="text-slate-700">→</span>}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [verdict, setVerdict] = useState<VerdictFilter>("all");
  const searchRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    fetchRuns().then(setRuns).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement !== searchRef.current) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const visible = useMemo(() => {
    if (!runs) return [];
    const q = query.toLowerCase();
    return runs
      .filter((r) => verdict === "all" || r.verdict === verdict)
      .filter(
        (r) =>
          !q ||
          r.run_id.toLowerCase().includes(q) ||
          (r.task ?? "").toLowerCase().includes(q) ||
          parseLabels(r.labels).some((l) => l.includes(q)),
      )
      .sort((a, b) => (b.started_at ?? 0) - (a.started_at ?? 0));
  }, [runs, query, verdict]);

  const counts = useMemo(() => {
    const c = { all: runs?.length ?? 0, pass: 0, warn: 0, fail: 0 };
    for (const r of runs ?? []) if (r.verdict && r.verdict in c) c[r.verdict as keyof typeof c]++;
    return c;
  }, [runs]);

  const toggle = (id: string) =>
    setPicked((p) =>
      p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id],
    );

  if (error)
    return (
      <div className="text-slate-400">
        <p className="text-red-400 font-mono mb-2">cannot reach the API</p>
        <p>
          Start it with <code className="text-slate-200">reflight serve</code>{" "}
          (expected at <code className="text-slate-200">{API}</code>)
        </p>
      </div>
    );
  if (!runs) return <p className="text-slate-500">loading…</p>;
  if (runs.length === 0)
    return (
      <p className="text-slate-400">
        No runs recorded yet — record one, then{" "}
        <code className="text-slate-200">reflight import</code>.
      </p>
    );

  const totalCost = visible.reduce((sum, r) => sum + (r.cost_usd ?? 0), 0);
  const passRate = visible.length
    ? visible.filter((r) => r.verdict === "pass").length / visible.length
    : 0;

  return (
    <div>
      <Landing />
      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="text-lg font-semibold">Runs</h1>
        <span className="font-mono text-xs text-slate-500">
          {visible.length} shown · {Math.round(passRate * 100)}% pass ·{" "}
          {fmtMoney(totalCost)} total
        </span>
        <input
          ref={searchRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="/ search id, task, label"
          className="w-56 rounded border border-slate-800 bg-slate-900/60 px-3 py-1 text-sm
                     text-slate-200 placeholder-slate-600 outline-none focus:border-slate-600"
        />
        <div className="flex gap-1">
          {(["all", "pass", "warn", "fail"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setVerdict(v)}
              className={`rounded px-2 py-0.5 font-mono text-xs ${
                verdict === v
                  ? (verdictStyle[v] ?? "bg-slate-700 text-slate-100") + " ring-1 ring-slate-500"
                  : "bg-slate-900 text-slate-500 hover:text-slate-300"
              }`}
            >
              {v} {counts[v]}
            </button>
          ))}
        </div>
        <button
          disabled={picked.length !== 2}
          onClick={() => router.push(`/diff?a=${picked[0]}&b=${picked[1]}`)}
          className="ml-auto rounded border border-slate-700 px-3 py-1 text-xs font-mono
                     text-slate-300 enabled:hover:bg-slate-800 disabled:opacity-40"
        >
          diff {picked.length}/2
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-slate-400 text-left">
            <tr>
              <th className="px-3 py-2"></th>
              <th className="px-4 py-2 font-medium">run</th>
              <th className="px-4 py-2 font-medium">agent</th>
              <th className="px-4 py-2 font-medium">verdict</th>
              <th className="px-4 py-2 font-medium">failure labels</th>
              <th className="px-4 py-2 font-medium">task</th>
              <th className="px-4 py-2 font-medium text-right">events</th>
              <th className="px-4 py-2 font-medium text-right">cost</th>
              <th className="px-4 py-2 font-medium">recorded</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((run) => (
              <tr
                key={run.run_id}
                className="border-t border-slate-800/70 hover:bg-slate-900/60"
              >
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={picked.includes(run.run_id)}
                    onChange={() => toggle(run.run_id)}
                    className="accent-cyan-500"
                  />
                </td>
                <td className="px-4 py-2 font-mono whitespace-nowrap">
                  <Link
                    href={`/runs/${run.run_id}`}
                    className="text-cyan-400 hover:text-cyan-300 hover:underline"
                  >
                    {run.run_id}
                  </Link>
                </td>
                <td className="px-4 py-2 whitespace-nowrap font-mono text-xs text-slate-500">
                  {run.agent ?? "—"}
                </td>
                <td className="px-4 py-2 whitespace-nowrap">
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-mono ${
                      verdictStyle[run.verdict ?? ""] ?? "bg-slate-800 text-slate-300"
                    }`}
                  >
                    {run.verdict ?? "?"}
                  </span>
                </td>
                <td className="px-4 py-2">
                  <div className="flex gap-1 whitespace-nowrap">
                    {parseLabels(run.labels)
                      .slice(0, 2)
                      .map((label) => (
                        <span
                          key={label}
                          className="rounded bg-slate-800 px-1.5 py-0.5 text-xs font-mono text-red-300"
                        >
                          {label}
                        </span>
                      ))}
                    {parseLabels(run.labels).length > 2 && (
                      <span className="px-1 py-0.5 text-xs font-mono text-slate-500">
                        +{parseLabels(run.labels).length - 2}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2 max-w-sm truncate text-slate-300">
                  {run.task}
                </td>
                <td className="px-4 py-2 text-right text-slate-400">
                  {run.event_count}
                </td>
                <td className="px-4 py-2 text-right font-mono text-slate-300">
                  {fmtCost(run.cost_usd)}
                </td>
                <td className="px-4 py-2 text-slate-500 text-xs whitespace-nowrap">
                  {fmtTime(run.started_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && (
          <p className="px-4 py-6 text-sm text-slate-500">
            nothing matches — clear the search or filters
          </p>
        )}
      </div>
    </div>
  );
}
