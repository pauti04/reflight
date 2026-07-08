"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchEvents, type AgentEvent, type EventRow } from "@/lib/api";

const RUN_ID = "flaky-01";
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
  const [shown, setShown] = useState(0);
  const [phase, setPhase] = useState<"play" | "verdict" | "hold">("play");
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    setReduced(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    fetchEvents(RUN_ID)
      .then(setRows)
      .catch(() => setRows([]));
  }, []);

  useEffect(() => {
    if (!rows.length) return;
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
  }, [rows, shown, phase, reduced]);

  if (!rows.length) return null;
  const visible = rows.slice(Math.max(0, shown - WINDOW), shown);
  const done = phase !== "play";

  return (
    <Link
      href={`/runs/${RUN_ID}`}
      className="block rounded-lg border border-zinc-800 bg-black font-mono text-xs
                 transition-colors hover:border-orange-800"
    >
      <div className="flex items-center gap-2 border-b border-zinc-800/80 px-4 py-2">
        <span className="rec-dot h-2 w-2 rounded-full bg-orange-500" />
        <span className="tracking-widest text-orange-400">
          {done ? "REPLAY FROM RECORDING" : "RECORDING"}
        </span>
        <span className="ml-auto text-zinc-600">
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
                    ? "text-zinc-600"
                    : "text-zinc-300"
              }
            >
              <span className="mr-2 text-zinc-700">
                {String(row.event.seq).padStart(2, "0")}
              </span>
              {text}
            </div>
          );
        })}
        {!done && (
          <span className="rec-dot inline-block h-3 w-1.5 bg-orange-500 align-text-bottom" />
        )}
      </div>

      <div
        className={`border-t border-zinc-800/80 px-4 py-2 transition-opacity duration-500 ${
          done ? "opacity-100" : "opacity-0"
        }`}
      >
        <div className="text-red-400">
          FINDING loop — calculator repeated 5 times with identical arguments (conf 0.95)
        </div>
        <div className="text-zinc-500">
          replayed from the recording · api calls 0 · cost $0.00 · click to step
          through it yourself
        </div>
      </div>
    </Link>
  );
}
