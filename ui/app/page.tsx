"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  API,
  STATIC,
  fetchRuns,
  fmtCost,
  fmtTime,
  parseLabels,
  verdictStyle,
  type Run,
} from "@/lib/api";

type VerdictFilter = "all" | "pass" | "warn" | "fail";

const TOUR_STOPS = [
  {
    href: "/runs/flaky-01",
    title: "An agent stuck in a loop",
    blurb: "5 identical calls, then a made-up answer — caught and labeled",
  },
  {
    href: "/diff?a=flaky-00&b=flaky-02",
    title: "Spot the bug in one diff",
    blurb: "pass vs fail, first divergence highlighted: query vs q",
  },
  {
    href: "/runs/runaway-budget",
    title: "Runaway killed at $0.50",
    blurb: "no turn limit — the governor's kill is recorded in the run",
  },
  {
    href: "/reliability",
    title: "The reliability scoreboard",
    blurb: "15 runs of one task: 47% pass, failure modes ranked",
  },
];

function DemoTour() {
  const [show, setShow] = useState(false);
  useEffect(() => {
    setShow(STATIC && !localStorage.getItem("reflight-tour-dismissed"));
  }, []);
  if (!show) return null;
  return (
    <div className="mb-5 rounded-lg border border-sky-900/60 bg-sky-950/20 p-4">
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <p className="text-sm text-zinc-300">
          These are <span className="text-zinc-100">real recorded agent runs</span> —
          every LLM call and tool call, replayable. Four worth a look:
        </p>
        <button
          onClick={() => {
            localStorage.setItem("reflight-tour-dismissed", "1");
            setShow(false);
          }}
          className="shrink-0 font-mono text-xs text-zinc-500 hover:text-zinc-200"
        >
          dismiss ✕
        </button>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {TOUR_STOPS.map((stop) => (
          <Link
            key={stop.href}
            href={stop.href}
            className="group rounded-md border border-zinc-800 bg-zinc-900/40 p-3
                       hover:border-sky-800 hover:bg-zinc-900"
          >
            <p className="mb-1 text-sm font-medium text-sky-300 group-hover:text-sky-200">
              {stop.title} →
            </p>
            <p className="text-xs leading-relaxed text-zinc-500">{stop.blurb}</p>
          </Link>
        ))}
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
      <div className="text-zinc-400">
        <p className="text-red-400 font-mono mb-2">cannot reach the API</p>
        <p>
          Start it with <code className="text-zinc-200">reflight serve</code>{" "}
          (expected at <code className="text-zinc-200">{API}</code>)
        </p>
      </div>
    );
  if (!runs) return <p className="text-zinc-500">loading…</p>;
  if (runs.length === 0)
    return (
      <p className="text-zinc-400">
        No runs recorded yet — record one, then{" "}
        <code className="text-zinc-200">reflight import</code>.
      </p>
    );

  const totalCost = visible.reduce((sum, r) => sum + (r.cost_usd ?? 0), 0);
  const passRate = visible.length
    ? visible.filter((r) => r.verdict === "pass").length / visible.length
    : 0;

  return (
    <div>
      <DemoTour />
      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="text-lg font-semibold">Runs</h1>
        <span className="font-mono text-xs text-zinc-500">
          {visible.length} shown · {Math.round(passRate * 100)}% pass ·{" "}
          {fmtCost(totalCost)} total
        </span>
        <input
          ref={searchRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="/ search id, task, label"
          className="w-56 rounded border border-zinc-800 bg-zinc-900/60 px-3 py-1 text-sm
                     text-zinc-200 placeholder-zinc-600 outline-none focus:border-zinc-600"
        />
        <div className="flex gap-1">
          {(["all", "pass", "warn", "fail"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setVerdict(v)}
              className={`rounded px-2 py-0.5 font-mono text-xs ${
                verdict === v
                  ? (verdictStyle[v] ?? "bg-zinc-700 text-zinc-100") + " ring-1 ring-zinc-500"
                  : "bg-zinc-900 text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {v} {counts[v]}
            </button>
          ))}
        </div>
        <button
          disabled={picked.length !== 2}
          onClick={() => router.push(`/diff?a=${picked[0]}&b=${picked[1]}`)}
          className="ml-auto rounded border border-zinc-700 px-3 py-1 text-xs font-mono
                     text-zinc-300 enabled:hover:bg-zinc-800 disabled:opacity-40"
        >
          diff {picked.length}/2
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
            {visible.map((run) => (
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
        {visible.length === 0 && (
          <p className="px-4 py-6 text-sm text-zinc-500">
            nothing matches — clear the search or filters
          </p>
        )}
      </div>
    </div>
  );
}
