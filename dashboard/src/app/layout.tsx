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
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full`}>
      <body className="flex min-h-full flex-col bg-background text-foreground antialiased">

        {/* Disclaimer banner */}
        <div
          role="note"
          className="border-b border-border bg-surface px-4 py-1.5 text-center text-xs text-muted-fg"
        >
          {DISCLAIMER}
        </div>

        {/* Header */}
        <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur-sm">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
            <Link
              href="/"
              className="group flex items-center gap-2.5 text-foreground no-underline"
            >
              {/* Wordmark */}
              <span className="relative font-semibold tracking-tight text-base">
                <span className="text-accent">Inter</span>
                <span className="text-foreground">lock</span>
              </span>
              {/* Tag */}
              <span className="hidden rounded border border-border bg-surface-muted px-1.5 py-0.5 text-[10px] font-medium tracking-widest text-muted-fg uppercase sm:inline">
                GraphRAG
              </span>
            </Link>

            <Nav />
          </div>
          {/* Accent line at bottom */}
          <div className="h-px bg-gradient-to-r from-transparent via-accent/40 to-transparent" />
        </header>

        {/* Main content */}
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
          {children}
        </main>

        {/* Footer */}
        <footer className="mt-auto border-t border-border px-4 py-4">
          <div className="mx-auto max-w-7xl flex flex-col items-center gap-1 text-center text-xs text-muted">
            <p>{DISCLAIMER}</p>
            <p className="text-muted/60">
              Built by{" "}
              <span className="text-accent font-medium">Hotty_Fi5e</span>
              {" · "}
              <a
                href="https://github.com/Tetra4ge/Interlock-TG"
                target="_blank"
                rel="noopener noreferrer"
                className="text-muted-fg hover:text-cyan transition-colors"
              >
                GitHub
              </a>
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
