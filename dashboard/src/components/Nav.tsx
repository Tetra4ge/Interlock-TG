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
    <nav aria-label="Main" className="flex flex-wrap gap-1 text-sm">
      {LINKS.map((l) => {
        const active = isActive(pathname, l.href);
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 font-medium transition-colors ${
              active
                ? "bg-accent text-background"
                : "text-muted hover:bg-surface-muted hover:text-foreground"
            }`}
          >
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
