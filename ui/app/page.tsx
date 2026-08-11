"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import FdrPanel from "@/components/fdr-panel";
import LoopTabs from "@/components/loop-tabs";
import {
  API,
  LABEL_HELP,
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

const STORY = [
  {
    n: "1",
    href: "/runs/refund-01",
    title: "An AI agent fumbles a refund",
    sub: "It sends $49.99 as text instead of a number — the refund system rejects it, and the AI retries the same broken call three times.",
  },
  {
    n: "2",
    href: "/diff?a=refund-00&b=refund-01",
    title: "The diff pinpoints the bug",
    sub: "A passing attempt and the failing one, side by side — identical until step 5, where the difference is highlighted.",
  },
  {
    n: "3",
    href: "/reliability",
    title: "Reflight spots it recurring",
    sub: "The same mistake shows up in another customer's run — one fingerprint links them as a single bug.",
  },
  {
    n: "4",
    href: "/runs/refund-runaway",
    title: "A runaway is stopped at $2.00",
    sub: "Another agent retried forever; Reflight's budget kill-switch ended the run and recorded exactly why.",
  },
];

function StatsBar() {
  const [stats, setStats] = useState<{ runs: number; agents: number; cost: number } | null>(null);
  useEffect(() => {
    fetchRuns()
      .then((runs) =>
        setStats({
          runs: runs.length,
          agents: new Set(runs.map((r) => r.agent ?? r.task)).size,
          cost: runs.reduce((sum, r) => sum + (r.cost_usd ?? 0), 0),
        }),
      )
      .catch(() => setStats(null));
  }, []);
  if (!stats) return null;
  const cells: [string, string][] = [
    [String(stats.runs), "recorded runs"],
    [String(stats.agents), "agents"],
    [fmtMoney(stats.cost), "total recorded spend"],
    ["$0.00", "to replay all of it"],
  ];
  return (
    <div className="mt-6 flex flex-wrap gap-x-8 gap-y-2 border-t border-slate-200 pt-4">
      {cells.map(([value, label]) => (
        <div key={label}>
          <div className="font-mono text-lg font-semibold text-slate-900">{value}</div>
          <div className="text-xs text-slate-500">{label}</div>
        </div>
      ))}
    </div>
  );
}

function Landing() {
  if (!STATIC) return null;
  return (
    <div className="gridbg -mx-6 mb-10 px-6">
      <div className="grid grid-cols-1 items-center gap-8 py-8 lg:grid-cols-2">
        <div>
          <h1 className="text-3xl font-bold leading-tight text-slate-900">
            Your agent failed at 2 a.m.
            <br />
            <span className="text-indigo-600">By morning, the failure was gone.</span>
          </h1>
          <p className="mt-4 text-slate-600">
            An AI agent is a program that lets an AI take real actions — look
            up an order, issue a refund, book a meeting. When one misbehaves,
            there is usually no record of what it did or why.{" "}
            <span className="font-medium text-slate-900">
              Reflight is the black box
            </span>
            : it records every step an agent takes, replays any run exactly as
            it happened, and turns failures into tests so they can never
            quietly return.
          </p>
          <p className="mt-3 text-sm text-slate-500">
            The panel on the right is a{" "}
            <span className="text-slate-800">real recording, replaying now</span>:
            an AI support agent handling a damaged-order refund. Lines marked
            LLM are the AI deciding what to do; lines marked TOOL are those
            decisions actually executing. Watch it send the amount as text —
            and fail three times. Nothing here is mocked.
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            <Link
              href="/runs/refund-01"
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white
                         transition-colors hover:bg-indigo-500"
            >
              Step through this failure
            </Link>
            <Link
              href="/diff?a=refund-00&b=refund-01"
              className="rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-800
                         transition-colors hover:border-indigo-400 hover:text-indigo-700"
            >
              Spot a bug in one diff
            </Link>
          </div>
          <StatsBar />
        </div>
        <FdrPanel />
      </div>

      <LoopTabs />

      <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
        <p className="mb-3 font-mono text-xs font-semibold uppercase tracking-wider text-slate-500">
          the story in this demo — follow one bug end to end
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {STORY.map((stop) => (
            <Link
              key={stop.href}
              href={stop.href}
              className="group rounded-md border border-slate-200 bg-white p-3
                         transition-colors hover:border-indigo-400"
            >
              <div className="mb-1 flex items-baseline gap-2">
                <span className="font-mono text-xs text-indigo-600">{stop.n}</span>
                <span
                  className="text-sm font-semibold text-slate-900 group-hover:text-indigo-700"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {stop.title}
                </span>
              </div>
              <p className="text-xs leading-relaxed text-slate-500">{stop.sub}</p>
            </Link>
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
      <div className="text-slate-500">
        <p className="text-red-600 font-mono mb-2">cannot reach the API</p>
        <p>
          Start it with <code className="text-slate-800">reflight serve</code>{" "}
          (expected at <code className="text-slate-800">{API}</code>)
        </p>
      </div>
    );
  if (!runs) return <p className="text-slate-500">loading…</p>;
  if (runs.length === 0)
    return (
      <p className="text-slate-500">
        No runs recorded yet — record one, then{" "}
        <code className="text-slate-800">reflight import</code>.
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
        <span className="hidden text-sm text-slate-500 md:inline">
          every row is one recorded agent session — click it to replay what the AI did
        </span>
        <span className="font-mono text-xs text-slate-500">
          {visible.length} shown · {Math.round(passRate * 100)}% pass ·{" "}
          {fmtMoney(totalCost)} total
        </span>
        <input
          ref={searchRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="/ search id, task, label"
          className="w-56 rounded border border-slate-300 bg-white px-3 py-1 text-sm
                     text-slate-800 placeholder-slate-400 outline-none focus:border-indigo-400"
        />
        <div className="flex gap-1">
          {(["all", "pass", "warn", "fail"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setVerdict(v)}
              className={`rounded px-2 py-0.5 font-mono text-xs ${
                verdict === v
                  ? (verdictStyle[v] ?? "bg-slate-700 text-slate-100") + " ring-1 ring-slate-400"
                  : "bg-slate-100 text-slate-500 hover:text-slate-800"
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
                     text-slate-700 enabled:hover:bg-slate-100 disabled:opacity-40"
        >
          diff {picked.length}/2
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-slate-600 text-left">
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
                className="border-t border-slate-200 hover:bg-indigo-50/40"
              >
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={picked.includes(run.run_id)}
                    onChange={() => toggle(run.run_id)}
                    className="accent-indigo-600"
                  />
                </td>
                <td className="px-4 py-2 font-mono whitespace-nowrap">
                  <Link
                    href={`/runs/${run.run_id}`}
                    className="text-indigo-600 hover:text-indigo-500 hover:underline"
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
                      verdictStyle[run.verdict ?? ""] ?? "bg-slate-100 text-slate-600"
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
                          title={LABEL_HELP[label] ?? label}
                          className="cursor-help rounded bg-red-50 px-1.5 py-0.5 text-xs font-mono text-red-700"
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
                <td className="px-4 py-2 max-w-sm truncate text-slate-700">
                  {run.task}
                </td>
                <td className="px-4 py-2 text-right text-slate-500">
                  {run.event_count}
                </td>
                <td className="px-4 py-2 text-right font-mono text-slate-700">
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
