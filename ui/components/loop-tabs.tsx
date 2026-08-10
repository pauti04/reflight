"use client";

import { useEffect, useState } from "react";
import { fetchRun } from "@/lib/api";

type Tab = {
  key: string;
  n: string;
  title: string;
  claim: string;
  body: (promotedYaml: string | null) => { lang: string; text: string };
  proof: string;
};

const RECORD_SNIPPET = `import reflight

session = reflight.record("runs/refund-01", db_path="runs/reflight.db")
client  = session.wrap(anthropic.Anthropic())   # 1 line: the client
issue_refund = session.tool(issue_refund)       # 1 line per tool

# ... your agent loop runs exactly as before — every LLM call, tool
# call, token and dollar now lands in runs/refund-01/events.jsonl`;

const REPLAY_SNIPPET = `$ python refund_agent.py --replay runs/refund-01

  replaying 13 events · network OFF · api spend $0.00
  seq 05  llm     issue_refund({... "amount_usd": "$49.99"})   HASH OK
  seq 06  tool    TypeError: amount_usd must be a number       SERVED
  ...
  run complete — byte-identical to the live recording

# change the prompt or code and replay refuses to lie:
# ReplayDivergence: LLM request at seq 5 differs from the recording`;

const TABS: Tab[] = [
  {
    key: "record",
    n: "01",
    title: "Record",
    claim: "Three added lines. Your agent code doesn't change.",
    body: () => ({ lang: "python", text: RECORD_SNIPPET }),
    proof: "this exact recording is run refund-01 on this site",
  },
  {
    key: "replay",
    n: "02",
    title: "Replay",
    claim: "The failure reproduces offline — every time, for free.",
    body: () => ({ lang: "console", text: REPLAY_SNIPPET }),
    proof: "hash-verified per event; a changed prompt raises, never lies",
  },
  {
    key: "test",
    n: "03",
    title: "Test",
    claim: "One command turns the failure into a pytest regression test.",
    body: (promotedYaml) => ({
      lang: "yaml",
      text:
        `$ reflight promote refund-01\n\n` +
        (promotedYaml
          ? promotedYaml.split("\n").slice(0, 12).join("\n") + "\n# ..."
          : "# tests/reflight/refund-01.yaml written"),
    }),
    proof: "passing tests replay at $0.00 — CI keeps the bug dead forever",
  },
];

export default function LoopTabs() {
  const [active, setActive] = useState(0);
  const [pinned, setPinned] = useState(false); // user clicked — stop auto-advance
  const [promotedYaml, setPromotedYaml] = useState<string | null>(null);

  useEffect(() => {
    fetchRun("refund-01")
      .then((run) => setPromotedYaml(run.promoted_yaml ?? null))
      .catch(() => setPromotedYaml(null));
  }, []);

  useEffect(() => {
    if (pinned) return;
    const timer = setTimeout(() => setActive((a) => (a + 1) % TABS.length), 6000);
    return () => clearTimeout(timer);
  }, [active, pinned]);

  const tab = TABS[active];
  const { text } = tab.body(promotedYaml);

  return (
    <div className="instrument rounded-lg border border-slate-800 bg-slate-950/80">
      <div className="flex border-b border-slate-800/80">
        {TABS.map((t, i) => (
          <button
            key={t.key}
            onClick={() => {
              setActive(i);
              setPinned(true);
            }}
            className={`relative flex-1 px-4 py-3 text-left transition-colors ${
              i === active ? "bg-slate-900/60" : "hover:bg-slate-900/40"
            }`}
          >
            <span
              className={`mr-2 font-mono text-xs ${
                i === active ? "text-cyan-400" : "text-slate-600"
              }`}
            >
              {t.n}
            </span>
            <span
              className={`text-sm font-semibold ${
                i === active ? "text-slate-100" : "text-slate-500"
              }`}
              style={{ fontFamily: "var(--font-display)" }}
            >
              {t.title}
            </span>
            {i === active && !pinned && (
              <span className="tab-progress absolute bottom-0 left-0 h-px bg-cyan-600/80" />
            )}
            {i === active && pinned && (
              <span className="absolute bottom-0 left-0 h-px w-full bg-cyan-600/80" />
            )}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-0 md:grid-cols-[240px_1fr]">
        <div className="border-b border-slate-800/60 p-4 md:border-b-0 md:border-r">
          <p className="text-sm leading-relaxed text-slate-300">{tab.claim}</p>
          <p className="mt-3 font-mono text-xs leading-relaxed text-slate-600">{tab.proof}</p>
        </div>
        <pre className="overflow-x-auto p-4 font-mono text-xs leading-6 text-slate-300">
          {text.split("\n").map((line, i) => (
            <div
              key={i}
              className={
                line.startsWith("#")
                  ? "text-slate-600"
                  : line.startsWith("$")
                    ? "text-cyan-300"
                    : line.includes("TypeError") || line.includes("ReplayDivergence")
                      ? "text-red-400"
                      : line.includes("HASH OK") ||
                          line.includes("byte-identical") ||
                          line.includes("$0.00")
                        ? "text-emerald-300"
                        : undefined
              }
            >
              {line || " "}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}
