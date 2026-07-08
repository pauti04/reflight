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
};

export type Run = {
  run_id: string;
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
  pass: "bg-emerald-900/60 text-emerald-300",
  warn: "bg-amber-900/60 text-amber-300",
  fail: "bg-red-900/60 text-red-300",
};

export const fmtCost = (c: number | null | undefined) =>
  c == null ? "—" : `$${c.toFixed(4)}`;

export const fmtTime = (ts: number | null) =>
  ts == null ? "—" : new Date(ts * 1000).toLocaleString();

export const fmtDuration = (start: number | null, end: number | null) => {
  if (start == null || end == null) return "—";
  const s = end - start;
  return s < 1 ? `${Math.round(s * 1000)}ms` : `${s.toFixed(1)}s`;
};
