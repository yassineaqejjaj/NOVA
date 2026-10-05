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
import { FolderKanban, History, Inbox, Library, ListTodo, LogOut, Moon, Orbit, Radar, Repeat, Search, Settings, Sparkles, Sun, Target, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { M as MM } from "@/components/missions/missions.messages";
import { PresencePill } from "@/components/missions/ui";
import { useMe } from "@/lib/api/hooks";
import { useInbox } from "@/lib/api/missions";
import { defineMessages, useT } from "@/lib/i18n";
import { useSystemLabel } from "@/lib/i18n/catalog";
import { useNovaState, useUi } from "@/stores/ui";

import { NovaLogo, NovaMark, PHASE_LABEL } from "./nova-mark";

const M = defineMessages({
  en: {
    home: "Home",
    projects: "Projects",
    tasks: "Tasks",
    library: "Library",
    context: "Context",
    skills: "Skills",
    timeline: "Timeline",
    workspace: "Workspace",
    knowledge: "Knowledge",
    nova: "NOVA",
    main: "Main",
    settings: "Settings",
    signOut: "Sign out",
    lightTheme: "Light theme",
    darkTheme: "Dark theme",
    accountMenu: "Account menu",
    search: "Search",
    searchAria: "Search (⌘K)",
  },
  fr: {
    home: "Accueil",
    projects: "Projets",
    tasks: "Tâches",
    library: "Bibliothèque",
    context: "Contexte",
    skills: "Compétences",
    timeline: "Timeline",
    workspace: "Espace de travail",
    knowledge: "Connaissances",
    nova: "NOVA",
    main: "Principal",
    settings: "Paramètres",
    signOut: "Se déconnecter",
    lightTheme: "Thème clair",
    darkTheme: "Thème sombre",
    accountMenu: "Menu du compte",
    search: "Rechercher",
    searchAria: "Rechercher (⌘K)",
  },
});
type Label = keyof typeof M.en;

type NavItem = { href: string; label: Label | MissionLabel; icon: "orb" | typeof FolderKanban; badge?: "inbox" };
type MissionLabel = keyof typeof MM.en;

/** NOVA as a team member first (Today, Goals, Missions, Tasks, Inbox), then the workspace, automation and activity. */
export const NAV_GROUPS: { label: MissionLabel; items: NavItem[] }[] = [
  {
    label: "navNova",
    items: [
      { href: "/", label: "today", icon: "orb" },
      { href: "/goals", label: "goals", icon: Target },
      { href: "/missions", label: "missions", icon: Radar },
      { href: "/work", label: "tasks", icon: ListTodo },
      { href: "/inbox", label: "inbox", icon: Inbox, badge: "inbox" },
    ],
  },
  {
    label: "navWorkspace",
    items: [
      { href: "/projects", label: "projects", icon: FolderKanban },
      { href: "/artifacts", label: "artifacts", icon: Library },
      { href: "/context", label: "knowledge", icon: Orbit },
    ],
  },
  {
    label: "navAutomation",
    items: [
      { href: "/skills", label: "skills", icon: Sparkles },
      { href: "/routines", label: "routines", icon: Repeat },
      { href: "/team", label: "team", icon: Users },
    ],
  },
  { label: "navActivity", items: [{ href: "/activity", label: "timeline", icon: History }] },
];

/** Bottom tab bar on phones (5 entries). */
export const NAV: NavItem[] = [
  { href: "/", label: "today", icon: "orb" },
  { href: "/goals", label: "goals", icon: Target },
  { href: "/inbox", label: "inbox", icon: Inbox, badge: "inbox" },
  { href: "/work", label: "tasks", icon: ListTodo },
  { href: "/artifacts", label: "artifacts", icon: Library },
];

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/" || pathname.startsWith("/c/");
  if (href === "/artifacts") return pathname.startsWith("/library") || pathname.startsWith("/artifacts");
  return pathname.startsWith(href);
}

function NavIcon({ icon, active, phase }: { icon: NavItem["icon"]; active: boolean; phase?: Parameters<typeof NovaMark>[0]["phase"] }) {
  if (icon === "orb") return <NovaMark size={18} phase={phase} />;
  const Icon = icon;
  return <Icon className={cn("size-[18px]", active ? "text-text" : "text-subtle")} />;
}

export function UserMenu({ compact = false }: { compact?: boolean }) {
  const t = useT(M);
  const { data: me } = useMe();
  const router = useRouter();
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  if (!me) return null;
  const logout = () => router.push("/logout"); // confirmation screen
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex w-full items-center gap-2.5 rounded-[12px] px-2 py-2 text-left hover:bg-surface-2" aria-label={t("accountMenu")}>
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
        <DropdownMenuItem onSelect={() => router.push("/settings")}><Settings /> {t("settings")}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? <Sun /> : <Moon />} {theme === "dark" ? t("lightTheme") : t("darkTheme")}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()}><LogOut /> {t("signOut")}</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function useNavLabel() {
  const t = useT(M);
  const tm = useT(MM);
  return (label: NavItem["label"]) => (label in MM.en ? tm(label as MissionLabel) : t(label as Label));
}

function InboxBadge() {
  const { data } = useInbox();
  const n = (data?.counts.decision ?? 0) + (data?.counts.validation ?? 0) + (data?.counts.anomaly ?? 0);
  return n ? <span className="ml-auto min-w-5 rounded-full bg-accent px-1.5 text-center text-[11px] font-semibold leading-5 text-white" data-testid="inbox-badge">{n}</span> : null;
}

export function Sidebar() {
  const t = useT(M);
  const navLabel = useNavLabel();
  const label = useSystemLabel();
  const pathname = usePathname();
  const running = useNovaState((s) => s.running);
  const current = Object.values(running)[0];
  return (
    <aside className="sticky top-0 hidden h-screen w-[224px] shrink-0 flex-col border-r border-border bg-surface px-3 py-5 md:flex">
      <Link href="/" className="mb-4 px-2">
        <NovaLogo height={26} />
      </Link>
      <PresencePill className="mb-4" />
      <nav className="flex flex-col gap-4 overflow-y-auto" aria-label={t("main")}>
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            <div className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-wider text-subtle">{navLabel(group.label)}</div>
            <div className="flex flex-col gap-0.5">
              {group.items.map((item) => {
                const active = isActive(pathname, item.href);
                const link = (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex h-9 items-center gap-3 rounded-[10px] px-3 text-[14px] transition-colors",
                      active ? "bg-surface-2 font-medium text-text" : "text-muted hover:bg-surface-2/70 hover:text-text",
                    )}
                  >
                    <NavIcon icon={item.icon} active={active} phase={item.icon === "orb" ? current?.phase : undefined} />
                    {navLabel(item.label)}
                    {item.badge === "inbox" ? <InboxBadge /> : null}
                  </Link>
                );
                return item.icon === "orb" && current ? (
                  <Tooltip key={item.href} content={current.label ? label(current.label) : PHASE_LABEL[current.phase]} side="right">{link}</Tooltip>
                ) : (
                  link
                );
              })}
            </div>
          </div>
        ))}
      </nav>
      <div className="mt-auto space-y-0.5">
        <Link
          href="/settings"
          className={cn(
            "flex h-9 items-center gap-3 rounded-[10px] px-3 text-[14px] transition-colors",
            pathname.startsWith("/settings") ? "bg-surface-2 font-medium text-text" : "text-muted hover:bg-surface-2/70 hover:text-text",
          )}
        >
          <Settings className="size-[18px] text-subtle" /> {t("settings")}
        </Link>
        <UserMenu />
      </div>
    </aside>
  );
}

/** Search finds what already exists (⌘K); asking NOVA to act happens in the composer. */
export function TopSearch() {
  const t = useT(M);
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  return (
    <button
      onClick={() => setPaletteOpen(true)}
      aria-label={t("searchAria")}
      className="flex h-9 items-center gap-2 rounded-full bg-surface-2/80 px-3.5 text-[13px] text-subtle transition-colors hover:bg-surface-3 hover:text-muted"
    >
      <Search className="size-4" />
      <span>{t("search")}</span>
      <Kbd className="ml-3">⌘K</Kbd>
    </button>
  );
}

export function MobileTabBar() {
  const navLabel = useNavLabel();
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
            {navLabel(item.label)}
          </Link>
        );
      })}
    </nav>
  );
}
