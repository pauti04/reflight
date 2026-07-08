import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

const HERO =
  "https://raw.githubusercontent.com/pauti04/reflight/main/docs/assets/hero-run.png";
const DESCRIPTION =
  "Flight recorder for AI agents: record every run, replay it deterministically, turn failures into regression tests.";

export const metadata: Metadata = {
  title: "Reflight — flight recorder for AI agents",
  description: DESCRIPTION,
  metadataBase: new URL("https://pauti04.github.io/reflight-demo/"),
  openGraph: {
    title: "Reflight — flight recorder for AI agents",
    description: DESCRIPTION,
    type: "website",
    images: [{ url: HERO, width: 1440, height: 820 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Reflight — flight recorder for AI agents",
    description: DESCRIPTION,
    images: [HERO],
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-screen bg-zinc-950 text-zinc-200 font-sans">
        <header className="border-b border-zinc-800 px-6 py-3 flex items-baseline gap-3">
          <Link href="/" className="font-mono font-bold text-zinc-50">
            ⏺ Reflight
          </Link>
          <span className="text-xs text-zinc-500">
            flight recorder for AI agents
          </span>
          {process.env.NEXT_PUBLIC_STATIC_DEMO === "1" && (
            <span className="rounded bg-sky-950/80 px-2 py-0.5 font-mono text-xs text-sky-300">
              read-only demo · pre-recorded runs
            </span>
          )}
          <nav className="ml-auto flex items-baseline gap-4 text-sm">
            <Link href="/" className="text-zinc-400 hover:text-zinc-100">
              runs
            </Link>
            <Link href="/reliability" className="text-zinc-400 hover:text-zinc-100">
              reliability
            </Link>
            <Link href="/costs" className="text-zinc-400 hover:text-zinc-100">
              costs
            </Link>
            <a
              href="https://github.com/pauti04/reflight"
              target="_blank"
              rel="noopener noreferrer"
              className="rounded border border-zinc-700 px-2 py-0.5 font-mono text-xs
                         text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100"
            >
              GitHub ↗
            </a>
          </nav>
        </header>
        <main className="px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
