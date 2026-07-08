import type { Metadata } from "next";
import { Geist, Geist_Mono, Space_Grotesk } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const display = Space_Grotesk({ variable: "--font-display", subsets: ["latin"] });

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
      className={`${geistSans.variable} ${geistMono.variable} ${display.variable} h-full antialiased`}
    >
      <body className="min-h-screen bg-zinc-950 text-zinc-200 font-sans">
        <header className="border-b border-zinc-800/80 px-6 py-3 flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2">
            <span className="rec-dot h-2.5 w-2.5 rounded-full bg-orange-500" />
            <span
              className="text-lg font-bold tracking-tight text-zinc-50"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Reflight
            </span>
          </Link>
          <span className="hidden text-xs text-zinc-500 sm:inline">
            the flight recorder for AI agents
          </span>
          {process.env.NEXT_PUBLIC_STATIC_DEMO === "1" && (
            <span className="rounded-full border border-orange-900/60 bg-orange-950/40 px-2.5 py-0.5 font-mono text-xs text-orange-300">
              demo · real recorded runs
            </span>
          )}
          <nav className="ml-auto flex items-center gap-4 text-sm">
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
              className="rounded-md border border-zinc-700 px-2.5 py-1 font-mono text-xs
                         text-zinc-200 transition-colors hover:border-orange-700
                         hover:bg-orange-950/40 hover:text-orange-200"
            >
              GitHub
            </a>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
