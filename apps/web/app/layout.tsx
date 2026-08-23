import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Trading Dashboard",
  description: "Paper-trading dashboard for the AI crypto trading platform",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        <header className="border-b border-zinc-200 dark:border-zinc-800">
          <div className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3">
            <Link href="/" className="font-semibold tracking-tight">
              Trading Dashboard
            </Link>
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              paper trading &middot; read-only market/account data
            </span>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
          {children}
        </main>
        <footer className="border-t border-zinc-200 px-4 py-3 text-center text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          Talks to the trading-api backend at{" "}
          <code>NEXT_PUBLIC_API_BASE_URL</code>. See{" "}
          <code>docs/DASHBOARD.md</code>.
        </footer>
      </body>
    </html>
  );
}
