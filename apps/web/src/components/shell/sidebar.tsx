"use client";

import {
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Kbd,
  Tooltip,
} from "@nova/ui";
import { Activity, FolderKanban, Library, ListTodo, LogOut, Moon, Orbit, Search, Settings, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import { useNovaState, useUi } from "@/stores/ui";

import { NovaLogo, NovaMark, PHASE_LABEL } from "./nova-mark";

export const NAV = [
  { href: "/", label: "NOVA", icon: "orb" as const },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/library", label: "Library", icon: Library },
  { href: "/activity", label: "Activity", icon: Activity },
];

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/" || pathname.startsWith("/c/");
  if (href === "/library") return pathname.startsWith("/library") || pathname.startsWith("/artifacts") || pathname.startsWith("/skills");
  if (href === "/activity") return pathname.startsWith("/activity") || pathname.startsWith("/work");
  return pathname.startsWith(href);
}

function NavIcon({ icon, active, phase }: { icon: (typeof NAV)[number]["icon"]; active: boolean; phase?: Parameters<typeof NovaMark>[0]["phase"] }) {
  if (icon === "orb") return <NovaMark size={18} phase={phase} />;
  const Icon = icon;
  return <Icon className={cn("size-[18px]", active ? "text-accent" : "text-subtle")} />;
}

export function UserMenu({ compact = false }: { compact?: boolean }) {
  const { data: me } = useMe();
  const router = useRouter();
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  if (!me) return null;
  const logout = async () => {
    const r = await api.post<{ redirect: string | null }>("/auth/logout");
    window.location.href = r.redirect ?? "/login";
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex w-full items-center gap-2.5 rounded-[12px] px-2 py-2 text-left hover:bg-surface-2" aria-label="Account menu">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-3 text-[13px] font-semibold text-text">
            {me.display_name.slice(0, 1).toUpperCase()}
          </span>
          {compact ? null : (
            <span className="min-w-0">
              <span className="block truncate text-[13px] font-medium text-text">{me.display_name}</span>
              <span className="block truncate text-[11.5px] text-subtle">{me.title || me.preferences.role || me.email}</span>
            </span>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-56">
        <DropdownMenuItem onSelect={() => router.push("/settings")}><Settings /> Settings</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => router.push("/context")}><Orbit /> ORBIT Context</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => router.push("/work")}><ListTodo /> Work</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? <Sun /> : <Moon />} {theme === "dark" ? "Light theme" : "Dark theme"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()}><LogOut /> Sign out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const running = useNovaState((s) => s.running);
  const current = Object.values(running)[0];
  return (
    <aside className="sticky top-0 hidden h-screen w-[224px] shrink-0 flex-col border-r border-border bg-surface px-3 py-5 md:flex">
      <Link href="/" className="mb-8 px-2">
        <NovaLogo height={26} />
      </Link>
      <nav className="flex flex-col gap-1">
        {NAV.map((item) => {
          const active = isActive(pathname, item.href);
          const link = (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex h-10 items-center gap-3 rounded-[12px] px-3 text-[14px] transition-colors",
                active ? "bg-accent-soft font-medium text-accent" : "text-muted hover:bg-surface-2 hover:text-text",
              )}
            >
              <NavIcon icon={item.icon} active={active} phase={item.icon === "orb" ? current?.phase : undefined} />
              {item.label}
            </Link>
          );
          return item.icon === "orb" && current ? (
            <Tooltip key={item.href} content={current.label || PHASE_LABEL[current.phase]} side="right">{link}</Tooltip>
          ) : (
            link
          );
        })}
      </nav>
      <div className="mt-auto">
        <UserMenu />
      </div>
    </aside>
  );
}

export function TopSearch() {
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  return (
    <button
      onClick={() => setPaletteOpen(true)}
      className="flex h-10 w-full max-w-[420px] items-center gap-2.5 rounded-full border border-border bg-surface px-4 text-[13.5px] text-subtle shadow-panel transition-colors hover:text-muted"
    >
      <Search className="size-4" />
      <span className="flex-1 text-left">Search anything…</span>
      <Kbd>⌘ K</Kbd>
    </button>
  );
}

export function MobileTabBar() {
  const pathname = usePathname();
  const running = useNovaState((s) => s.running);
  const current = Object.values(running)[0];
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex h-16 items-stretch border-t border-border bg-surface/95 backdrop-blur md:hidden">
      {NAV.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link key={item.href} href={item.href} className={cn("flex flex-1 flex-col items-center justify-center gap-1 text-[11px]", active ? "text-accent" : "text-subtle")}>
            <NavIcon icon={item.icon} active={active} phase={item.icon === "orb" ? current?.phase : undefined} />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
