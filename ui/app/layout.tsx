import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "AgentScope",
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
            ⏺ AgentScope
          </Link>
          <span className="text-xs text-zinc-500">
            flight recorder for AI agents
          </span>
        </header>
        <main className="px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
