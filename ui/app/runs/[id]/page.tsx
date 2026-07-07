import fs from "node:fs";
import path from "node:path";
import RunView from "@/components/run-view";

// Static export builds one page per demo run (data baked in by
// `reflight export-static`). In live mode this list is irrelevant —
// any run id resolves at request time.
export function generateStaticParams(): { id: string }[] {
  try {
    const raw = fs.readFileSync(
      path.join(process.cwd(), "public", "demo", "runs.json"),
      "utf-8",
    );
    return (JSON.parse(raw) as { run_id: string }[]).map((r) => ({ id: r.run_id }));
  } catch {
    return [];
  }
}

export default async function RunPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <RunView id={id} />;
}
