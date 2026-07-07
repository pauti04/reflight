import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Reflight",
  description: "Flight recorder for AI agents",
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
          <nav className="ml-auto flex gap-4 text-sm">
            <Link href="/" className="text-zinc-400 hover:text-zinc-100">
              runs
            </Link>
            <Link href="/reliability" className="text-zinc-400 hover:text-zinc-100">
              reliability
            </Link>
            <Link href="/costs" className="text-zinc-400 hover:text-zinc-100">
              costs
            </Link>
          </nav>
        </header>
        <main className="px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
