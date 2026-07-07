import type { NextConfig } from "next";

// STATIC_EXPORT=1 builds the zero-backend demo site (out/): data comes from
// public/demo/*.json snapshots. NEXT_PUBLIC_BASE_PATH supports subpath hosts
// like GitHub Pages project sites.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  ...(process.env.STATIC_EXPORT === "1"
    ? { output: "export" as const, trailingSlash: true }
    : {}),
  ...(basePath ? { basePath } : {}),
};

export default nextConfig;
