import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import AuthBadge from "@/components/AuthBadge";
import AuthGate from "@/components/AuthGate";
import AuthProvider from "@/components/AuthProvider";
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
        {/* AuthProvider wraps the header too, so the badge and the gated
            content always agree about who is signed in — a header that
            still shows an email after the session died is worse than no
            header at all. */}
        <AuthProvider>
          <header className="border-b border-zinc-200 dark:border-zinc-800">
            <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
              <Link href="/" className="font-semibold tracking-tight">
                Trading Dashboard
              </Link>
              <span className="text-xs text-zinc-500 dark:text-zinc-400">
                paper trading &middot; read-only market/account data
              </span>
              <div className="ml-auto">
                <AuthBadge />
              </div>
            </div>
          </header>
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
            <AuthGate>{children}</AuthGate>
          </main>
        </AuthProvider>
        <footer className="border-t border-zinc-200 px-4 py-3 text-center text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          Talks to the trading-api backend at{" "}
          <code>NEXT_PUBLIC_API_BASE_URL</code>. See{" "}
          <code>docs/DASHBOARD.md</code>.
        </footer>
      </body>
    </html>
  );
}
