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
import {
  FolderKanban,
  History,
  Inbox,
  Library,
  ListTodo,
  LogOut,
  Moon,
  Orbit,
  PanelLeftClose,
  PanelLeftOpen,
  Radar,
  Repeat,
  Search,
  Settings,
  Sparkles,
  Sun,
  Target,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

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
    collapse: "Collapse the menu",
    expand: "Expand the menu",
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
    collapse: "Réduire le menu",
    expand: "Déplier le menu",
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

function InboxBadge({ compact = false }: { compact?: boolean }) {
  const { data } = useInbox();
  const n = (data?.counts.decision ?? 0) + (data?.counts.validation ?? 0) + (data?.counts.anomaly ?? 0);
  if (!n) return null;
  return (
    <span
      data-testid="inbox-badge"
      className={cn(
        "rounded-full bg-accent text-center font-semibold text-white",
        compact ? "absolute -right-0.5 -top-0.5 min-w-4 px-1 text-[10px] leading-4" : "ml-auto min-w-5 px-1.5 text-[11px] leading-5",
      )}
    >
      {n}
    </span>
  );
}

/** The collapsed state lives in localStorage: apply it after mount so server and client render the same first. */
function useCollapsed(): [boolean, () => void] {
  const stored = useUi((s) => s.sidebarCollapsed);
  const toggle = useUi((s) => s.toggleSidebar);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "\\") {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);
  return [mounted && stored, toggle];
}

export function Sidebar() {
  const t = useT(M);
  const navLabel = useNavLabel();
  const label = useSystemLabel();
  const pathname = usePathname();
  const running = useNovaState((s) => s.running);
  const current = Object.values(running)[0];
  const [collapsed, toggle] = useCollapsed();
  const itemClass = (active: boolean) =>
    cn(
      "relative flex h-9 items-center rounded-[10px] text-[14px] transition-colors",
      collapsed ? "justify-center" : "gap-3 px-3",
      active ? "bg-surface-2 font-medium text-text" : "text-muted hover:bg-surface-2/70 hover:text-text",
    );
  // Collapsed: the label moves to a tooltip (and stays readable by screen readers).
  const withTip = (key: string, tip: React.ReactNode, node: React.ReactElement) =>
    collapsed || tip !== null ? (
      <Tooltip key={key} content={tip} side="right">
        {node}
      </Tooltip>
    ) : (
      node
    );
  const toggleLabel = collapsed ? t("expand") : t("collapse");
  return (
    <aside
      data-collapsed={collapsed || undefined}
      className={cn(
        "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border bg-surface py-5 transition-[width] duration-200 md:flex",
        collapsed ? "w-[64px] px-2" : "w-[224px] px-3",
      )}
    >
      <div className={cn("mb-4 flex items-center", collapsed ? "flex-col gap-3" : "justify-between pl-2")}>
        <Link href="/" aria-label="NOVA">
          {collapsed ? <NovaMark size={26} /> : <NovaLogo height={26} />}
        </Link>
        <Tooltip content={<span>{toggleLabel} <Kbd className="ml-1">{"⌘\\"}</Kbd></span>} side="right">
          <button
            onClick={toggle}
            aria-label={toggleLabel}
            aria-expanded={!collapsed}
            className="flex size-8 items-center justify-center rounded-[10px] text-subtle transition-colors hover:bg-surface-2 hover:text-text"
          >
            {collapsed ? <PanelLeftOpen className="size-[18px]" /> : <PanelLeftClose className="size-[18px]" />}
          </button>
        </Tooltip>
      </div>
      <PresencePill className="mb-4" compact={collapsed} />
      <nav className="flex flex-col gap-4 overflow-y-auto overflow-x-hidden" aria-label={t("main")}>
        {NAV_GROUPS.map((group, index) => (
          <div key={group.label}>
            {collapsed ? (
              index ? <div className="mx-2 mb-2 h-px bg-border" /> : null
            ) : (
              <div className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-wider text-subtle">{navLabel(group.label)}</div>
            )}
            <div className="flex flex-col gap-0.5">
              {group.items.map((item) => {
                const active = isActive(pathname, item.href);
                const name = navLabel(item.label);
                const phase = item.icon === "orb" && current ? (current.label ? label(current.label) : PHASE_LABEL[current.phase]) : null;
                const link = (
                  <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined} className={itemClass(active)}>
                    <NavIcon icon={item.icon} active={active} phase={item.icon === "orb" ? current?.phase : undefined} />
                    <span className={collapsed ? "sr-only" : undefined}>{name}</span>
                    {item.badge === "inbox" ? <InboxBadge compact={collapsed} /> : null}
                  </Link>
                );
                const tip = collapsed ? (phase ? `${name} · ${phase}` : name) : phase;
                return withTip(item.href, tip, link);
              })}
            </div>
          </div>
        ))}
      </nav>
      <div className="mt-auto space-y-0.5">
        {withTip(
          "settings",
          collapsed ? t("settings") : null,
          <Link href="/settings" className={itemClass(pathname.startsWith("/settings"))}>
            <Settings className="size-[18px] text-subtle" />
            <span className={collapsed ? "sr-only" : undefined}>{t("settings")}</span>
          </Link>,
        )}
        <UserMenu compact={collapsed} />
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
