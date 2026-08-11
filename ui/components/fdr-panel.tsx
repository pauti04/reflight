"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  fetchEvents,
  fetchRun,
  type AgentEvent,
  type EventRow,
  type Finding,
} from "@/lib/api";

const RUN_ID = "refund-01";
const TICK_MS = 520;
const VERDICT_HOLD_MS = 3200;
const RESTART_HOLD_MS = 1600;
const WINDOW = 8;

function line(event: AgentEvent): { text: string; tone: "dim" | "normal" | "bad" } {
  switch (event.type) {
    case "run_start":
      return { text: `TASK  ${event.task}`, tone: "dim" };
    case "llm_call": {
      const blocks = event.response?.content ?? [];
      const tool = blocks.find((b: AgentEvent) => b.type === "tool_use");
      if (tool)
        return {
          text: `LLM   requests ${tool.name}(${JSON.stringify(tool.input)})`,
          tone: "normal",
        };
      const text = blocks.find((b: AgentEvent) => b.type === "text")?.text ?? "";
      return { text: `LLM   "${text.slice(0, 52)}"`, tone: "normal" };
    }
    case "tool_call":
      return {
        text: `TOOL  ${event.name} returns ${String(event.result).slice(0, 40)}`,
        tone: event.is_error ? "bad" : "normal",
      };
    case "error":
      return { text: `HALT  ${event.error_type}: ${event.message}`, tone: "bad" };
    case "run_end":
      return { text: `END   status=${event.status}`, tone: "dim" };
    default:
      return { text: event.type, tone: "dim" };
  }
}

export default function FdrPanel() {
  const [rows, setRows] = useState<EventRow[]>([]);
  const [finding, setFinding] = useState<Finding | null>(null);
  const [shown, setShown] = useState(0);
  const [phase, setPhase] = useState<"play" | "verdict" | "hold">("play");
  const [scrubbed, setScrubbed] = useState(false); // user grabbed the timeline
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    setReduced(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    fetchEvents(RUN_ID)
      .then(setRows)
      .catch(() => setRows([]));
    fetchRun(RUN_ID)
      .then((run) => setFinding(run.findings?.[0] ?? null))
      .catch(() => setFinding(null));
  }, []);

  useEffect(() => {
    if (!rows.length || scrubbed) return;
    if (reduced) {
      setShown(rows.length);
      setPhase("verdict");
      return;
    }
    let timer: ReturnType<typeof setTimeout>;
    if (phase === "play") {
      timer =
        shown >= rows.length
          ? setTimeout(() => setPhase("verdict"), TICK_MS)
          : setTimeout(() => setShown((s) => s + 1), TICK_MS);
    } else if (phase === "verdict") {
      timer = setTimeout(() => setPhase("hold"), VERDICT_HOLD_MS);
    } else {
      timer = setTimeout(() => {
        setShown(0);
        setPhase("play");
      }, RESTART_HOLD_MS);
    }
    return () => clearTimeout(timer);
  }, [rows, shown, phase, reduced, scrubbed]);

  if (!rows.length) return null;
  const visible = rows.slice(Math.max(0, shown - WINDOW), shown);
  const done = phase !== "play";

  return (
    <Link
      href={`/runs/${RUN_ID}`}
      className="instrument block rounded-lg border border-slate-800 bg-slate-950 font-mono text-xs
                 transition-colors hover:border-indigo-400"
    >
      <div className="flex items-center gap-2 border-b border-slate-800/80 px-4 py-2">
        <span className="rec-dot h-2 w-2 rounded-full bg-indigo-400" />
        <span className="tracking-widest text-indigo-300">
          {done ? "REPLAY FROM RECORDING" : "RECORDING"}
        </span>
        <span className="ml-auto text-slate-600">
          run {RUN_ID} · event {Math.min(shown, rows.length)}/{rows.length}
        </span>
      </div>

      <div className="h-52 overflow-hidden px-4 py-3 leading-6">
        {visible.map((row) => {
          const { text, tone } = line(row.event);
          return (
            <div
              key={row.event.seq}
              className={
                tone === "bad"
                  ? "text-red-400"
                  : tone === "dim"
                    ? "text-slate-600"
                    : "text-slate-300"
              }
            >
              <span className="mr-2 text-slate-700">
                {String(row.event.seq).padStart(2, "0")}
              </span>
              {text}
            </div>
          );
        })}
        {!done && (
          <span className="rec-dot inline-block h-3 w-1.5 bg-indigo-400 align-text-bottom" />
        )}
      </div>

      {/* the scrubber: one tick per recorded event — grab the timeline */}
      <div
        className="flex items-end gap-px border-t border-slate-800/80 px-4 pb-1.5 pt-2"
        onClick={(e) => e.preventDefault()}
      >
        {rows.map((row, i) => {
          const { tone } = line(row.event);
          const lit = i < shown;
          return (
            <button
              key={row.event.seq}
              aria-label={`event ${i}`}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setScrubbed(true);
                setPhase("play");
                setShown(i + 1);
              }}
              className={`h-2 flex-1 rounded-sm transition-all hover:h-3 ${
                i === shown - 1
                  ? "h-3 bg-indigo-400"
                  : lit
                    ? tone === "bad"
                      ? "bg-red-700"
                      : "bg-slate-600"
                    : "bg-slate-800"
              }`}
            />
          );
        })}
      </div>

      <div
        className={`border-t border-slate-800/80 px-4 py-2 transition-opacity duration-500 ${
          done || scrubbed ? "opacity-100" : "opacity-0"
        }`}
      >
        {finding && (
          <div className="text-red-400">
            FINDING {finding.label} — {finding.detail.slice(0, 110)} (conf{" "}
            {finding.confidence.toFixed(2)})
          </div>
        )}
        <div className="flex items-baseline gap-2 text-slate-500">
          <span>
            {scrubbed
              ? "scrubbing the recording — every tick is a real event"
              : "replayed from the recording · api calls 0 · cost $0.00"}
          </span>
          {scrubbed ? (
            <button
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setScrubbed(false);
              }}
              className="rounded border border-slate-700 px-1.5 text-indigo-300 hover:border-indigo-400"
            >
              RESUME
            </button>
          ) : (
            <span>· click to step through it yourself</span>
          )}
        </div>
      </div>
    </Link>
  );
}
