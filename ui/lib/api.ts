export const API =
  process.env.NEXT_PUBLIC_REFLIGHT_API ?? "http://127.0.0.1:8724";

// Static demo mode: no backend — data comes from JSON snapshots baked into
// the build by `reflight export-static` (served under BASE/demo/).
export const STATIC = process.env.NEXT_PUBLIC_STATIC_DEMO === "1";
export const BASE = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export type Finding = {
  seq: number;
  label: string;
  severity: "fail" | "warn";
  confidence: number;
  detail: string;
  signature?: string;
  seen_in?: string[]; // other runs with the same bug fingerprint
};

export type RecurringFailure = {
  signature: string;
  label: string;
  detail: string;
  count: number;
  run_ids: string[];
  first_seen: number;
  last_seen: number;
};

export type Run = {
  run_id: string;
  agent: string | null;
  task: string | null;
  status: string | null;
  verdict: "pass" | "warn" | "fail" | null;
  labels: string | null; // JSON array
  findings?: Finding[];
  promoted_yaml?: string | null; // static demo: what `reflight promote` writes
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
  const base = STATIC ? BASE : API;
  const res = await fetch(`${base}${path}`, { cache: "no-store" });
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

export const fetchRuns = () =>
  STATIC ? get<Run[]>("/demo/runs.json") : get<Run[]>("/api/runs");

export const fetchRun = async (id: string): Promise<Run> => {
  if (!STATIC) return get<Run>(`/api/runs/${id}`);
  const run = (await fetchRuns()).find((r) => r.run_id === id);
  if (!run) throw new Error(`no run ${id}`);
  return run;
};

export const fetchEvents = (id: string) =>
  STATIC
    ? get<EventRow[]>(`/demo/events/${id}.json`)
    : get<EventRow[]>(`/api/runs/${id}/events`);

export const fetchDiff = async (a: string, b: string): Promise<Diff> => {
  if (!STATIC)
    return get<Diff>(`/api/diff?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  const { diffRuns } = await import("./static-diff");
  const [rowsA, rowsB] = await Promise.all([fetchEvents(a), fetchEvents(b)]);
  return diffRuns(
    rowsA.map((r) => r.event),
    rowsB.map((r) => r.event),
  );
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const fetchCosts = (): Promise<any> =>
  STATIC ? get("/demo/costs.json") : get("/api/costs");

export const fetchRecurring = (): Promise<RecurringFailure[]> =>
  STATIC ? get("/demo/recurring.json") : get("/api/recurring");

export type Promoted = { path: string; yaml: string };

export async function promoteRun(id: string): Promise<Promoted> {
  if (STATIC) throw new Error("read-only demo — clone the repo to promote runs");
  const res = await fetch(`${API}/api/runs/${id}/promote`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} promoting ${id}`);
  return res.json();
}

export const parseLabels = (labels: string | null): string[] => {
  try {
    return labels ? JSON.parse(labels) : [];
  } catch {
    return [];
  }
};

export const verdictStyle: Record<string, string> = {
  pass: "bg-emerald-100 text-emerald-800",
  warn: "bg-amber-100 text-amber-800",
  fail: "bg-red-100 text-red-700",
};

export const fmtCost = (c: number | null | undefined) =>
  c == null ? "—" : `$${c.toFixed(4)}`;

// for totals: dollars-and-cents once the amount is big enough to read that way
export const fmtMoney = (c: number | null | undefined) =>
  c == null ? "—" : c >= 0.1 ? `$${c.toFixed(2)}` : `$${c.toFixed(4)}`;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const fmtTime = (ts: number | null) => {
  if (ts == null) return "—";
  const d = new Date(ts * 1000);
  const h = d.getHours() % 12 || 12;
  const ampm = d.getHours() < 12 ? "AM" : "PM";
  return `${MONTHS[d.getMonth()]} ${d.getDate()} · ${h}:${String(d.getMinutes()).padStart(2, "0")} ${ampm}`;
};

export const fmtDuration = (start: number | null, end: number | null) => {
  if (start == null || end == null) return "—";
  const s = end - start;
  return s < 1 ? `${Math.round(s * 1000)}ms` : `${s.toFixed(1)}s`;
};
