import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import Nav from "@/components/Nav";
import { DISCLAIMER } from "@/lib/pipelines";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Interlock – RAG vs GraphRAG vs Agentic GraphRAG",
  description:
    "Comparing three retrieval architectures on Indian corporate-governance disclosures, with confidence intervals, costs and failure analysis.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <div role="note" className="bg-warn-bg px-4 py-1.5 text-center text-xs text-warn-fg">
          {DISCLAIMER}
        </div>
        <header className="border-b border-border bg-surface">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
            <Link href="/" className="text-lg font-semibold tracking-tight">
              Interlock
            </Link>
            <Nav />
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
        <footer className="border-t border-border px-4 py-3 text-center text-xs text-muted">
          {DISCLAIMER}
        </footer>
      </body>
    </html>
  );
}
