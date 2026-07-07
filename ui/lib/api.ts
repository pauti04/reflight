export const API =
  process.env.NEXT_PUBLIC_AGENTSCOPE_API ?? "http://127.0.0.1:8724";

export type Finding = {
  seq: number;
  label: string;
  severity: "fail" | "warn";
  confidence: number;
  detail: string;
};

export type Run = {
  run_id: string;
  task: string | null;
  status: string | null;
  verdict: "pass" | "warn" | "fail" | null;
  labels: string | null; // JSON array
  findings?: Finding[];
  started_at: number | null;
  ended_at: number | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  final_text: string | null;
  event_count: number;
  tool_errors: number;
  run_dir: string;
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AgentEvent = Record<string, any>;

export type EventRow = { event: AgentEvent; cost_usd: number | null };

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} from ${path}`);
  return res.json();
}

export type Diff = {
  divergence_seq: number | null;
  identical: boolean;
  a_len: number;
  b_len: number;
  a: AgentEvent[];
  b: AgentEvent[];
};

export const fetchRuns = () => get<Run[]>("/api/runs");
export const fetchRun = (id: string) => get<Run>(`/api/runs/${id}`);
export const fetchEvents = (id: string) =>
  get<EventRow[]>(`/api/runs/${id}/events`);
export const fetchDiff = (a: string, b: string) =>
  get<Diff>(`/api/diff?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);

export const parseLabels = (labels: string | null): string[] => {
  try {
    return labels ? JSON.parse(labels) : [];
  } catch {
    return [];
  }
};

export const verdictStyle: Record<string, string> = {
  pass: "bg-emerald-900/60 text-emerald-300",
  warn: "bg-amber-900/60 text-amber-300",
  fail: "bg-red-900/60 text-red-300",
};

export const fmtCost = (c: number | null | undefined) =>
  c == null ? "—" : `$${c.toFixed(4)}`;

export const fmtTime = (ts: number | null) =>
  ts == null ? "—" : new Date(ts * 1000).toLocaleString();
