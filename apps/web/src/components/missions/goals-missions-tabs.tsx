"use client";

import { cn } from "@nova/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useT } from "@/lib/i18n";

import { M } from "./missions.messages";

/** Goals and Missions share one menu entry: two views of what NOVA is pursuing. */
export function GoalsMissionsTabs() {
  const t = useT(M);
  const pathname = usePathname();
  const tabs = [
    { href: "/goals", label: t("goals") },
    { href: "/missions", label: t("missions") },
  ];
  return (
    <nav className="mb-4 flex gap-1 rounded-[12px] bg-surface-2 p-1 w-fit" aria-label={`${t("goals")} / ${t("missions")}`}>
      {tabs.map((tab) => {
        const active = pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn("rounded-[9px] px-3.5 py-1.5 text-[13px] transition-colors", active ? "bg-surface font-medium text-text shadow-sm" : "text-muted hover:text-text")}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
