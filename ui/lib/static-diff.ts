// Client-side run diffing for the static demo (no backend to ask).
// Mirrors sdk/reflight/diff.py: events are "the same" when their signature
// matches. We compare canonical JSON instead of hashes — equality is equality.

import type { AgentEvent, Diff } from "./api";

// identifiers, not behavior — mirrors VOLATILE_KEYS in sdk/reflight/diff.py
const VOLATILE_KEYS = new Set(["id", "created", "system_fingerprint", "tool_use_id"]);

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalize(value: any): any {
  if (value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map(normalize);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const out: Record<string, any> = {};
  for (const key of Object.keys(value)) {
    if (!VOLATILE_KEYS.has(key)) out[key] = normalize(value[key]);
  }
  return out;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function canon(value: any): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canon).join(",")}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canon(value[k])}`).join(",")}}`;
}

function signature(event: AgentEvent): string {
  switch (event.type) {
    case "llm_call":
      return `llm|${canon(normalize(event.request))}|${canon(normalize(event.response))}`;
    case "tool_call":
      return `tool|${event.name}|${event.input_hash}|${canon(normalize(event.result))}|${event.is_error}`;
    case "run_start":
      return `start|${event.task}`;
    case "run_end":
      return `end|${event.status}|${event.final_text}`;
    case "state_snapshot":
      return `snap|${event.label}|${event.state_hash}`;
    default:
      return String(event.type);
  }
}

export function diffRuns(a: AgentEvent[], b: AgentEvent[]): Diff {
  let divergence: number | null = null;
  const shared = Math.min(a.length, b.length);
  for (let i = 0; i < shared; i++) {
    if (signature(a[i]) !== signature(b[i])) {
      divergence = i;
      break;
    }
  }
  return {
    divergence_seq: divergence,
    identical: divergence === null && a.length === b.length,
    a_len: a.length,
    b_len: b.length,
    a,
    b,
  };
}
