"use client";

import { cn } from "@nova/ui";
import { ChevronRight } from "lucide-react";
import { type CSSProperties, type ReactNode, useMemo, useState } from "react";

import type { ArtifactItem } from "@/lib/api/types";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    fidelity: "Fidelity",
    auto: "Auto",
    wireframe: "Wireframe",
    lowfi: "Low-fi",
    hifi: "High-fi",
    gallery: "Screens preview",
    screenLabel: (v: { name: string; device: string; fidelity: string }) => `${v.name}, ${v.device}, ${v.fidelity}`,
    mobile: "Mobile",
    tablet: "Tablet",
    desktop: "Desktop",
    states: "States",
    noElements: "No elements described for this screen yet.",
    untitled: "Untitled screen",
    editAsData: "Edit screens as data",
    hideData: "Hide data editor",
    noScreens: "No screens yet.",
  },
  fr: {
    fidelity: "Fidélité",
    auto: "Auto",
    wireframe: "Wireframe",
    lowfi: "Lo-fi",
    hifi: "Hi-fi",
    gallery: "Aperçu des écrans",
    screenLabel: (v: { name: string; device: string; fidelity: string }) => `${v.name}, ${v.device}, ${v.fidelity}`,
    mobile: "Mobile",
    tablet: "Tablette",
    desktop: "Ordinateur",
    states: "États",
    noElements: "Aucun élément décrit pour cet écran.",
    untitled: "Écran sans titre",
    editAsData: "Modifier les écrans comme données",
    hideData: "Masquer l’éditeur de données",
    noScreens: "Aucun écran pour l’instant.",
  },
});

type Fidelity = "wireframe" | "lowfi" | "hifi";
type Device = "mobile" | "tablet" | "desktop";
type Region = "header" | "sidebar" | "body" | "footer";

interface El {
  id: string;
  type: string;
  label: string;
  region: Region;
  row: number | null;
  span: number | null;
  variant: string;
  state: string;
}

const FIDELITIES: Fidelity[] = ["wireframe", "lowfi", "hifi"];
const DEVICE_WIDTH: Record<Device, number> = { mobile: 280, tablet: 440, desktop: 680 };
const DEVICE_MIN_HEIGHT: Record<Device, number> = { mobile: 540, tablet: 520, desktop: 400 };

const str = (v: unknown): string => (typeof v === "string" ? v : typeof v === "number" ? String(v) : "");
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function toFidelity(v: unknown): Fidelity | null {
  return v === "wireframe" || v === "lowfi" || v === "hifi" ? v : null;
}
function toDevice(v: unknown): Device {
  return v === "tablet" || v === "desktop" ? v : "mobile";
}

/** Defensive parse of `attributes.elements`: anything malformed is skipped or defaulted. */
function parseElements(raw: unknown): El[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((r, i): El[] => {
    if (!r || typeof r !== "object") return [];
    const o = r as Record<string, unknown>;
    const type = str(o.type) || "text";
    const regionRaw = str(o.region);
    const region: Region =
      regionRaw === "header" || regionRaw === "sidebar" || regionRaw === "body" || regionRaw === "footer"
        ? regionRaw
        : type === "header" ? "header" : type === "footer" ? "footer" : "body";
    const span = num(o.span);
    return [{
      id: str(o.id) || `el-${i}`,
      type,
      label: str(o.label),
      region,
      row: num(o.row),
      span: span === null ? null : Math.min(12, Math.max(1, Math.round(span))),
      variant: str(o.variant),
      state: str(o.state),
    }];
  });
}

/** Rows of a region ordered by `row`; elements sharing a row sit side by side. Rows without `row` keep their own line. */
function toRows(els: El[]): El[][] {
  const rows = new Map<string, El[]>();
  const order: { key: string; row: number; i: number }[] = [];
  els.forEach((el, i) => {
    const key = el.row === null ? `i${i}` : `r${el.row}`;
    if (!rows.has(key)) {
      rows.set(key, []);
      order.push({ key, row: el.row ?? Number.MAX_SAFE_INTEGER, i });
    }
    rows.get(key)!.push(el);
  });
  order.sort((a, b) => a.row - b.row || a.i - b.i);
  return order.map((o) => rows.get(o.key)!);
}

// ---- Theme ---------------------------------------------------------------------------------------------------------

interface Theme {
  mode: Fidelity;
  bg: string;
  surface: string;
  fg: string;
  muted: string;
  border: string;
  primary: string;
  primaryFg: string;
  danger: string;
  radius: number;
  font: string;
}

const COLOR_RE = /^(#[0-9a-f]{3,8}|(rgb|hsl)a?\([^)]*\))$/i;
const validColor = (v: string): string | null => (COLOR_RE.test(v.trim()) ? v.trim() : null);

function readableOn(color: string): string {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})/i.exec(color);
  if (!m) return "#ffffff";
  const hex = m[1] ?? "";
  const h = hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex;
  const [r = 0, g = 0, b = 0] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return (r * 299 + g * 587 + b * 114) / 1000 > 160 ? "#111111" : "#ffffff";
}

function buildTheme(mode: Fidelity, tokens: ArtifactItem[]): Theme {
  const base: Theme = {
    mode,
    bg: "#ffffff",
    surface: "#f4f4f5",
    fg: "#18181b",
    muted: "#71717a",
    border: "#d4d4d8",
    primary: "#27272a",
    primaryFg: "#ffffff",
    danger: "#dc2626",
    radius: 6,
    font: "system-ui, -apple-system, sans-serif",
  };
  if (mode === "wireframe") return { ...base, surface: "#e5e7eb", fg: "#6b7280", muted: "#9ca3af", border: "#9ca3af", primary: "#9ca3af", primaryFg: "#ffffff", danger: "#6b7280", radius: 3 };
  if (mode === "lowfi") return base;
  // hi-fi: tokens applied when parseable, polished fallbacks otherwise.
  const hifi: Theme = { ...base, primary: "#4f46e5", surface: "#f5f5fb", border: "#e4e4ee", muted: "#64748b", radius: 12 };
  const colors = tokens.filter((t) => str(t.attributes?.category) === "color").map((t) => ({ name: `${t.title} ${str(t.attributes?.usage)}`.toLowerCase(), value: validColor(str(t.attributes?.value)) })).filter((c): c is { name: string; value: string } => !!c.value);
  const pick = (re: RegExp) => colors.find((c) => re.test(c.name))?.value;
  hifi.primary = pick(/primary|brand|accent/) ?? colors[0]?.value ?? hifi.primary;
  hifi.bg = pick(/background|\bbg\b|canvas/) ?? hifi.bg;
  hifi.surface = pick(/surface|card|neutral-?[0-9]*\b/) ?? hifi.surface;
  hifi.fg = pick(/text|foreground|ink|on-?surface/) ?? hifi.fg;
  hifi.border = pick(/border|outline|divider|stroke/) ?? hifi.border;
  hifi.danger = pick(/danger|error|destructive|red/) ?? hifi.danger;
  hifi.primaryFg = readableOn(hifi.primary);
  const radius = tokens.find((t) => str(t.attributes?.category) === "radius");
  const r = radius ? parseFloat(str(radius.attributes?.value)) : NaN;
  if (Number.isFinite(r)) hifi.radius = Math.min(28, Math.max(0, r));
  const type = tokens.find((t) => str(t.attributes?.category) === "typography");
  const fam = type ? /^["']?([A-Za-z][A-Za-z0-9 ]{1,30}?)["']?\s*(?:[,/·|]|\d|$)/.exec(str(type.attributes?.value).trim())?.[1]?.trim() : undefined;
  if (fam && !/^(bold|medium|regular|light|semibold)$/i.test(fam)) hifi.font = `"${fam}", system-ui, -apple-system, sans-serif`;
  return hifi;
}

// ---- Element renderers ---------------------------------------------------------------------------------------------

const parts = (label: string): string[] => label.split(/[|·]/).map((s) => s.trim()).filter(Boolean);
const DEFAULT_LABEL: Record<string, string> = {
  heading: "Title", text: "Body text", button: "Button", input: "Input", select: "Select", checkbox: "Option", toggle: "Toggle", list: "Item",
  card: "Card", table: "Table", chart: "Chart", image: "Image", icon: "•", nav: "Home|Search|Profile", tabs: "Tab 1|Tab 2|Tab 3", chip: "Tag",
  banner: "Notice", modal: "Dialog", footer: "Footer", header: "Header", divider: "",
};

function Bar({ th, w = "100%", h = 6 }: { th: Theme; w?: string | number; h?: number }) {
  return <div style={{ width: w, height: h, borderRadius: 3, background: th.mode === "wireframe" ? th.surface : th.border }} />;
}

function ImageBox({ th, label, ratio = "16 / 9" }: { th: Theme; label: string; ratio?: string }) {
  return (
    <div role="img" aria-label={label || "image"} style={{ position: "relative", width: "100%", aspectRatio: ratio, minHeight: 36, background: th.surface, border: `1px solid ${th.border}`, borderRadius: th.radius, overflow: "hidden" }}>
      <svg width="100%" height="100%" preserveAspectRatio="none" style={{ position: "absolute", inset: 0 }} aria-hidden>
        <line x1="0" y1="0" x2="100%" y2="100%" stroke={th.border} strokeWidth="1" />
        <line x1="100%" y1="0" x2="0" y2="100%" stroke={th.border} strokeWidth="1" />
      </svg>
      {label ? <span style={{ position: "absolute", left: 6, bottom: 4, fontSize: 9, color: th.muted, background: th.surface, padding: "0 3px", borderRadius: 2 }}>{label}</span> : null}
    </div>
  );
}

function Element({ el, th }: { el: El; th: Theme }) {
  const wire = th.mode === "wireframe";
  const label = el.label || DEFAULT_LABEL[el.type] || "";
  const disabled = el.state === "disabled";
  const error = el.state === "error";
  const focus = el.state === "focus";
  const selected = el.state === "selected";
  const stateStyle: CSSProperties = {
    opacity: disabled ? 0.45 : 1,
    outline: focus ? `2px solid ${wire ? th.muted : th.primary}` : undefined,
    outlineOffset: focus ? 2 : undefined,
  };
  const borderColor = error ? th.danger : selected ? th.primary : th.border;
  const field: CSSProperties = {
    border: `1px ${wire ? "dashed" : "solid"} ${borderColor}`,
    borderRadius: th.radius,
    padding: "6px 8px",
    background: selected ? `color-mix(in srgb, ${th.primary} 10%, ${th.bg})` : th.bg,
    color: error && !wire ? th.danger : th.muted,
    fontSize: 11,
    minHeight: 28,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 6,
    ...stateStyle,
  };
  const small = { fontSize: wire ? 10 : 11 } as const;
  const wrap = (node: ReactNode) => <div data-el={el.type} data-state={el.state || undefined} style={{ minWidth: 0 }}>{node}</div>;

  switch (el.type) {
    case "header":
      return wrap(<div style={{ fontWeight: 600, fontSize: 13, color: wire ? th.muted : th.fg, ...stateStyle }}>{label}</div>);
    case "heading":
      return wrap(wire ? (
        <div style={stateStyle}><div style={{ fontSize: 10, color: th.muted, marginBottom: 3 }}>{label}</div><Bar th={th} w="60%" h={10} /></div>
      ) : (
        <div style={{ fontSize: th.mode === "hifi" ? 17 : 15, fontWeight: 700, letterSpacing: "-0.01em", color: th.fg, ...stateStyle }}>{label}</div>
      ));
    case "text":
      return wrap(wire ? (
        <div style={{ ...stateStyle, display: "grid", gap: 4 }}><div style={{ fontSize: 10, color: th.muted }}>{label}</div><Bar th={th} /><Bar th={th} w="80%" /></div>
      ) : (
        <p style={{ margin: 0, fontSize: 11.5, lineHeight: 1.45, color: th.muted, ...stateStyle }}>{label}</p>
      ));
    case "button": {
      const v = el.variant || "primary";
      const filled = v === "primary" || v === "danger";
      const color = v === "danger" ? th.danger : th.primary;
      return wrap(
        <div
          role="presentation"
          style={{
            display: "inline-flex", alignItems: "center", justifyContent: "center", minHeight: 28, padding: "0 12px", borderRadius: th.radius, fontSize: 11, fontWeight: 600, width: "100%",
            background: wire ? (filled ? th.surface : "transparent") : filled ? color : v === "secondary" ? th.surface : "transparent",
            color: wire ? th.muted : filled ? (v === "danger" ? "#fff" : th.primaryFg) : v === "ghost" ? color : th.fg,
            border: wire ? `1px dashed ${th.border}` : v === "secondary" ? `1px solid ${th.border}` : "1px solid transparent",
            boxShadow: th.mode === "hifi" && filled ? `0 1px 2px color-mix(in srgb, ${color} 40%, transparent)` : undefined,
            ...stateStyle,
          }}
        >{label}</div>,
      );
    }
    case "input":
      return wrap(<div style={field}><span>{label}</span></div>);
    case "select":
      return wrap(<div style={field}><span>{label}</span><span aria-hidden>▾</span></div>);
    case "checkbox":
      return wrap(
        <div style={{ display: "flex", alignItems: "center", gap: 6, ...small, color: th.fg, ...stateStyle }}>
          <span style={{ width: 14, height: 14, borderRadius: Math.min(4, th.radius), border: `1px ${wire ? "dashed" : "solid"} ${borderColor}`, background: selected && !wire ? th.primary : th.bg, color: th.primaryFg, fontSize: 10, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>{selected && !wire ? "✓" : ""}</span>
          <span style={{ color: wire ? th.muted : th.fg }}>{label}</span>
        </div>,
      );
    case "toggle":
      return wrap(
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, ...small, color: wire ? th.muted : th.fg, ...stateStyle }}>
          <span>{label}</span>
          <span style={{ width: 28, height: 16, borderRadius: 9, background: selected ? (wire ? th.muted : th.primary) : th.border, position: "relative", flexShrink: 0 }}>
            <span style={{ position: "absolute", top: 2, left: selected ? 14 : 2, width: 12, height: 12, borderRadius: 6, background: "#fff" }} />
          </span>
        </div>,
      );
    case "list": {
      const rows = parts(label);
      const items = rows.length > 1 ? rows : [rows[0] ?? "Item", "", ""];
      return wrap(
        <ul style={{ listStyle: "none", margin: 0, padding: 0, border: `1px ${wire ? "dashed" : "solid"} ${th.border}`, borderRadius: th.radius, ...stateStyle }}>
          {items.map((it, i) => (
            <li key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 8px", borderTop: i ? `1px ${wire ? "dashed" : "solid"} ${th.border}` : undefined, fontSize: 11, color: wire ? th.muted : th.fg }}>
              <span style={{ width: 14, height: 14, borderRadius: 7, background: th.surface, flexShrink: 0 }} />
              {it ? <span>{it}</span> : <Bar th={th} w="60%" />}
            </li>
          ))}
        </ul>,
      );
    }
    case "card":
      return wrap(
        <div style={{ border: `1px ${wire ? "dashed" : "solid"} ${borderColor}`, borderRadius: th.radius, padding: 10, background: th.mode === "hifi" ? th.bg : th.mode === "lowfi" ? th.bg : "transparent", display: "grid", gap: 6, boxShadow: th.mode === "hifi" ? "0 1px 3px rgba(0,0,0,.08)" : undefined, ...stateStyle }}>
          <div style={{ fontSize: 11.5, fontWeight: 600, color: wire ? th.muted : th.fg }}>{label}</div>
          <Bar th={th} /><Bar th={th} w="70%" />
        </div>,
      );
    case "table": {
      const cols = parts(label);
      const heads = cols.length > 1 ? cols : ["Name", "Status", "Date"];
      return wrap(
        <div style={{ border: `1px ${wire ? "dashed" : "solid"} ${th.border}`, borderRadius: th.radius, overflow: "hidden", fontSize: 10.5, ...stateStyle }}>
          <div style={{ display: "grid", gridTemplateColumns: `repeat(${heads.length}, 1fr)`, background: th.surface, color: th.fg, fontWeight: 600 }}>
            {heads.map((h, i) => <div key={i} style={{ padding: "5px 8px" }}>{h}</div>)}
          </div>
          {[0, 1, 2].map((r) => (
            <div key={r} style={{ display: "grid", gridTemplateColumns: `repeat(${heads.length}, 1fr)`, borderTop: `1px ${wire ? "dashed" : "solid"} ${th.border}` }}>
              {heads.map((_, i) => <div key={i} style={{ padding: "7px 8px" }}><Bar th={th} w={i === 0 ? "75%" : "50%"} /></div>)}
            </div>
          ))}
          {cols.length === 1 ? <div style={{ padding: "4px 8px", color: th.muted }}>{cols[0]}</div> : null}
        </div>,
      );
    }
    case "chart":
      return wrap(
        <div style={{ border: `1px ${wire ? "dashed" : "solid"} ${th.border}`, borderRadius: th.radius, padding: 8, ...stateStyle }}>
          <div style={{ fontSize: 10.5, color: th.muted, marginBottom: 6 }}>{label}</div>
          <div aria-hidden style={{ display: "flex", alignItems: "flex-end", gap: 5, height: 56 }}>
            {[40, 65, 50, 85, 60, 95].map((h, i) => <div key={i} style={{ flex: 1, height: `${h}%`, background: wire ? th.surface : th.primary, opacity: wire ? 1 : 0.35 + (i % 3) * 0.2, borderRadius: `${Math.min(4, th.radius)}px ${Math.min(4, th.radius)}px 0 0` }} />)}
          </div>
        </div>,
      );
    case "image":
      return wrap(<ImageBox th={th} label={label} />);
    case "icon":
      return wrap(<span aria-label={label || "icon"} role="img" style={{ display: "inline-flex", width: 24, height: 24, borderRadius: 12, alignItems: "center", justifyContent: "center", background: th.surface, color: wire ? th.muted : th.primary, fontSize: 11, border: wire ? `1px dashed ${th.border}` : undefined, ...stateStyle }}>{label.length <= 2 ? label || "•" : label[0]}</span>);
    case "nav": {
      const links = parts(label);
      return wrap(
        <nav aria-hidden style={{ display: "flex", flexWrap: "wrap", gap: 12, fontSize: 11, color: wire ? th.muted : th.muted, ...stateStyle }}>
          {(links.length ? links : ["Home"]).map((l, i) => <span key={i} style={{ color: i === 0 && !wire ? th.primary : th.muted, fontWeight: i === 0 ? 600 : 400 }}>{l}</span>)}
        </nav>,
      );
    }
    case "tabs": {
      const tabs = parts(label);
      return wrap(
        <div aria-hidden style={{ display: "flex", gap: 0, borderBottom: `1px ${wire ? "dashed" : "solid"} ${th.border}`, fontSize: 11, ...stateStyle }}>
          {(tabs.length ? tabs : ["Tab"]).map((tb, i) => <span key={i} style={{ padding: "6px 10px", marginBottom: -1, borderBottom: `2px solid ${i === 0 ? (wire ? th.muted : th.primary) : "transparent"}`, color: i === 0 ? (wire ? th.muted : th.fg) : th.muted, fontWeight: i === 0 ? 600 : 400 }}>{tb}</span>)}
        </div>,
      );
    }
    case "chip":
      return wrap(<span style={{ display: "inline-block", padding: "2px 9px", borderRadius: 999, fontSize: 10.5, background: selected && !wire ? th.primary : th.surface, color: selected && !wire ? th.primaryFg : th.muted, border: wire ? `1px dashed ${th.border}` : undefined, ...stateStyle }}>{label}</span>);
    case "banner": {
      const tint = el.variant === "danger" || error ? th.danger : th.primary;
      return wrap(<div role="note" style={{ padding: "8px 10px", borderRadius: th.radius, fontSize: 11, color: wire ? th.muted : th.fg, background: wire ? "transparent" : `color-mix(in srgb, ${tint} 12%, ${th.bg})`, border: `1px ${wire ? "dashed" : "solid"} ${wire ? th.border : `color-mix(in srgb, ${tint} 35%, transparent)`}`, ...stateStyle }}>{label}</div>);
    }
    case "modal":
      return wrap(
        <div style={{ border: `1px ${wire ? "dashed" : "solid"} ${th.border}`, borderRadius: th.radius + 2, padding: 12, background: th.bg, boxShadow: wire ? undefined : "0 8px 24px rgba(0,0,0,.18)", display: "grid", gap: 8, ...stateStyle }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, color: wire ? th.muted : th.fg }}>{label}</div>
          <Bar th={th} /><Bar th={th} w="65%" />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
            <span style={{ padding: "3px 10px", fontSize: 10.5, color: th.muted }}>Cancel</span>
            <span style={{ padding: "3px 10px", fontSize: 10.5, borderRadius: th.radius, background: wire ? th.surface : th.primary, color: wire ? th.muted : th.primaryFg }}>OK</span>
          </div>
        </div>,
      );
    case "footer":
      return wrap(<div style={{ textAlign: "center", fontSize: 10, color: th.muted, ...stateStyle }}>{label}</div>);
    case "divider":
      return wrap(<hr style={{ border: 0, borderTop: `1px ${wire ? "dashed" : "solid"} ${th.border}`, margin: "2px 0" }} />);
    default:
      // Unknown element type: a labelled placeholder rather than a crash.
      return wrap(<div style={{ border: `1px dashed ${th.border}`, borderRadius: th.radius, padding: "6px 8px", fontSize: 10.5, color: th.muted, ...stateStyle }}>{label || el.type}</div>);
  }
}

function RegionRows({ els, th, gap = 10 }: { els: El[]; th: Theme; gap?: number }) {
  if (!els.length) return null;
  return (
    <div style={{ display: "grid", gap }}>
      {toRows(els).map((row, i) => {
        const explicit = row.reduce((s, e) => s + (e.span ?? 0), 0);
        const fallback = Math.max(1, Math.floor(12 / row.length));
        return (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "repeat(12, minmax(0, 1fr))", gap: 8, alignItems: "start" }}>
            {row.map((el) => <div key={el.id} style={{ gridColumn: `span ${el.span ?? (explicit ? Math.max(1, Math.floor((12 - explicit) / Math.max(1, row.filter((e) => e.span === null).length))) : fallback)}` }}><Element el={el} th={th} /></div>)}
          </div>
        );
      })}
    </div>
  );
}

// ---- Frame ---------------------------------------------------------------------------------------------------------

function Frame({ item, mode, tokens }: { item: ArtifactItem; mode: Fidelity; tokens: ArtifactItem[] }) {
  const t = useT(M);
  const a = item.attributes ?? {};
  const device = toDevice(a.device);
  const th = useMemo(() => buildTheme(mode, tokens), [mode, tokens]);
  const els = useMemo(() => parseElements(a.elements), [a.elements]);
  const by = (r: Region) => els.filter((e) => e.region === r);
  const header = by("header"), sidebar = by("sidebar"), body = by("body"), footer = by("footer");
  const name = item.title || t("untitled");
  const states = str(a.states).split(",").map((s) => s.trim()).filter(Boolean);
  const purpose = str(a.purpose) || item.description;
  const label = t("screenLabel", { name, device: t(device), fidelity: t(mode) });
  const split = sidebar.length > 0 && device !== "mobile";

  return (
    <figure className="m-0 shrink-0 snap-start" style={{ width: DEVICE_WIDTH[device] }}>
      <div
        role="group"
        aria-label={label}
        style={{
          width: DEVICE_WIDTH[device], minHeight: DEVICE_MIN_HEIGHT[device], background: th.bg, color: th.fg, fontFamily: th.font, display: "flex", flexDirection: "column",
          border: `${device === "mobile" ? 6 : 4}px solid #27272a`, borderRadius: device === "mobile" ? 28 : device === "tablet" ? 20 : 10, overflow: "hidden",
          boxShadow: "0 8px 24px rgba(0,0,0,.18)",
        }}
      >
        {device === "desktop" ? <div aria-hidden style={{ display: "flex", gap: 4, padding: "6px 8px", background: "#e4e4e7" }}>{[0, 1, 2].map((i) => <span key={i} style={{ width: 7, height: 7, borderRadius: 4, background: "#a1a1aa" }} />)}</div> : null}
        {device === "mobile" ? <div aria-hidden style={{ height: 18, display: "flex", justifyContent: "center", alignItems: "flex-end" }}><span style={{ width: 60, height: 4, borderRadius: 2, background: th.border }} /></div> : null}
        {header.length ? <div style={{ padding: "10px 12px", borderBottom: `1px ${th.mode === "wireframe" ? "dashed" : "solid"} ${th.border}` }}><RegionRows els={header} th={th} gap={6} /></div> : null}
        <div style={{ display: split ? "grid" : "block", gridTemplateColumns: split ? "26% 1fr" : undefined, flex: 1 }}>
          {sidebar.length ? <div style={{ padding: 12, background: th.mode === "wireframe" ? "transparent" : th.surface, borderRight: split ? `1px ${th.mode === "wireframe" ? "dashed" : "solid"} ${th.border}` : undefined, borderBottom: split ? undefined : `1px solid ${th.border}` }}><RegionRows els={sidebar} th={th} gap={8} /></div> : null}
          <div style={{ padding: 12, minWidth: 0 }}>
            {body.length ? <RegionRows els={body} th={th} /> : !header.length && !sidebar.length && !footer.length ? <p style={{ margin: 0, fontSize: 11, color: th.muted }}>{t("noElements")}</p> : null}
          </div>
        </div>
        {footer.length ? <div style={{ padding: "8px 12px", borderTop: `1px ${th.mode === "wireframe" ? "dashed" : "solid"} ${th.border}` }}><RegionRows els={footer} th={th} gap={6} /></div> : null}
      </div>
      <figcaption className="mt-2 space-y-1 text-[12.5px]">
        <div className="font-medium text-text">{name}</div>
        {purpose ? <p className="m-0 text-muted">{purpose}</p> : null}
        {states.length ? (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[11.5px] text-subtle">{t("states")}</span>
            {states.map((s) => <span key={s} className="rounded-full bg-surface-3 px-1.5 py-0.5 text-[11px] text-muted">{s}</span>)}
          </div>
        ) : null}
      </figcaption>
    </figure>
  );
}

// ---- Public component ----------------------------------------------------------------------------------------------

/**
 * Visual preview of a `ui_screens` artifact's `screens` section. `allItems` is every item of the artifact, from which
 * the `design_token` items drive the hi-fi style. `children` (the raw items editor) is kept in a collapsible block.
 */
export function ScreensPreview({ items, allItems, children }: { items: ArtifactItem[]; allItems: ArtifactItem[]; children?: ReactNode }) {
  const t = useT(M);
  const [override, setOverride] = useState<Fidelity | null>(null);
  const [dataOpen, setDataOpen] = useState(false);
  const tokens = useMemo(() => allItems.filter((i) => i.kind === "design_token"), [allItems]);
  const screens = items.filter((i) => i.kind === "screen");
  const options: { value: Fidelity | null; label: string }[] = [{ value: null, label: t("auto") }, ...FIDELITIES.map((f) => ({ value: f as Fidelity | null, label: t(f) }))];

  return (
    <div className="space-y-3">
      {screens.length ? (
        <>
          <div role="radiogroup" aria-label={t("fidelity")} className="inline-flex rounded-full bg-surface-2 p-0.5">
            {options.map((o) => (
              <button
                key={o.label}
                role="radio"
                aria-checked={override === o.value}
                onClick={() => setOverride(o.value)}
                className={cn("rounded-full px-3 py-1 text-[12px] transition-colors", override === o.value ? "bg-surface font-medium text-text shadow-sm" : "text-subtle hover:text-text")}
              >
                {o.label}
              </button>
            ))}
          </div>
          <div role="region" aria-label={t("gallery")} tabIndex={0} className="-mx-1 flex snap-x gap-5 overflow-x-auto px-1 pb-3 pt-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50">
            {screens.map((s) => <Frame key={s.id} item={s} mode={override ?? toFidelity(s.attributes?.fidelity) ?? "lowfi"} tokens={tokens} />)}
          </div>
        </>
      ) : (
        <p className="text-[13px] text-subtle">{t("noScreens")}</p>
      )}
      {children ? (
        <div>
          <button onClick={() => setDataOpen(!dataOpen)} aria-expanded={dataOpen} className="flex items-center gap-1 text-[12.5px] text-subtle hover:text-text">
            <ChevronRight className={cn("size-3.5 transition-transform", dataOpen && "rotate-90")} />
            {dataOpen ? t("hideData") : t("editAsData")}
          </button>
          {dataOpen ? <div className="mt-2">{children}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
