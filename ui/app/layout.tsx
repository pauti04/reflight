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
      <body className="min-h-screen bg-background text-foreground font-sans">
        <header className="border-b border-slate-200/80 px-6 py-3 flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2">
            <span className="rec-dot h-2.5 w-2.5 rounded-full bg-indigo-500" />
            <span
              className="text-lg font-bold tracking-tight text-slate-900"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Reflight
            </span>
          </Link>
          <span className="hidden text-xs text-slate-500 sm:inline">
            the flight recorder for AI agents
          </span>
          {process.env.NEXT_PUBLIC_STATIC_DEMO === "1" && (
            <span className="rounded-full border border-indigo-200/60 bg-indigo-50 px-2.5 py-0.5 font-mono text-xs text-indigo-600">
              demo · real recorded runs
            </span>
          )}
          <nav className="ml-auto flex items-center gap-4 text-sm">
            <Link href="/" className="text-slate-500 hover:text-slate-900">
              runs
            </Link>
            <Link href="/reliability" className="text-slate-500 hover:text-slate-900">
              reliability
            </Link>
            <Link href="/costs" className="text-slate-500 hover:text-slate-900">
              costs
            </Link>
            <a
              href="https://github.com/pauti04/reflight"
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-md border border-slate-300 px-2.5 py-1 font-mono text-xs
                         text-slate-800 transition-colors hover:border-indigo-400
                         hover:bg-indigo-50 hover:text-indigo-700"
            >
              GitHub
            </a>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
        <footer className="mx-auto mt-12 max-w-6xl border-t border-slate-200 px-6 py-6">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-xs text-slate-500">
            <span className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-indigo-600" />
              Reflight — every run on this site is a real recording
            </span>
            <a
              href="https://github.com/pauti04/reflight"
              className="hover:text-slate-800"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub
            </a>
            <a
              href="https://pypi.org/project/reflight/"
              className="hover:text-slate-800"
              target="_blank"
              rel="noopener noreferrer"
            >
              pip install reflight
            </a>
            <a
              href="https://github.com/pauti04/reflight/blob/main/docs/format.md"
              className="hover:text-slate-800"
              target="_blank"
              rel="noopener noreferrer"
            >
              recording format
            </a>
            <a
              href="https://github.com/pauti04/reflight/blob/main/docs/case-study.md"
              className="hover:text-slate-800"
              target="_blank"
              rel="noopener noreferrer"
            >
              case study
            </a>
          </div>
        </footer>
      </body>
    </html>
  );
}
