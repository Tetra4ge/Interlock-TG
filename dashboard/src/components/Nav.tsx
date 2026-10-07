"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/tradeoffs", label: "Trade-offs" },
  { href: "/failures", label: "Failures" },
  { href: "/inspector", label: "Inspector" },
  { href: "/live", label: "Live ask" },
  { href: "/data-quality", label: "Data quality" },
  { href: "/review-queue", label: "Review queue" },
];

export function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex flex-wrap items-center gap-0.5 text-sm">
      {LINKS.map((l) => {
        const active = isActive(pathname, l.href);
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={[
              "relative px-3 py-1.5 rounded-md font-medium transition-colors duration-150",
              active
                ? "text-accent bg-accent-dim"
                : "text-muted-fg hover:text-foreground hover:bg-surface-muted",
            ].join(" ")}
          >
            {l.label}
            {active && (
              <span
                aria-hidden
                className="absolute inset-x-2 bottom-0.5 h-px rounded-full bg-accent"
              />
            )}
          </Link>
        );
      })}
    </nav>
  );
}
