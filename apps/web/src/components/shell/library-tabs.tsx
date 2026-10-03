"use client";

import { cn } from "@nova/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/artifacts", label: "Artifacts" },
  { href: "/skills", label: "Skills" },
];

/** Library = everything NOVA produced (Artifacts) and every method it can use (Skills). */
export function LibraryTabs() {
  const pathname = usePathname();
  return (
    <nav aria-label="Library" className="mb-6 flex gap-1 border-b border-border">
      {TABS.map((t) => {
        const active = pathname.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={cn("-mb-px border-b-2 px-3 pb-2.5 text-[13.5px] font-medium", active ? "border-accent text-text" : "border-transparent text-subtle hover:text-text")}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
