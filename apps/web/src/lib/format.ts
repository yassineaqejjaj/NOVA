import { getLang } from "@/lib/i18n";

const locale = () => (getLang() === "fr" ? "fr-FR" : "en-GB");

export function timeAgo(iso: string): string {
  const fr = getLang() === "fr";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return fr ? "à l’instant" : "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return fr ? `il y a ${minutes} min` : `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return fr ? `il y a ${hours} h` : `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return fr ? "hier" : "yesterday";
  if (days < 7) return fr ? `il y a ${days} jours` : `${days} days ago`;
  return new Date(iso).toLocaleDateString(locale(), { day: "numeric", month: "short" });
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
}

/** Full date and time in the interface language ("5 Oct 2026, 14:05" / "5 oct. 2026, 14:05"). */
export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString(locale(), { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function dayLabel(iso: string): string {
  const fr = getLang() === "fr";
  const date = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return fr ? "Aujourd’hui" : "Today";
  if (date.toDateString() === yesterday.toDateString()) return fr ? "Hier" : "Yesterday";
  const label = date.toLocaleDateString(locale(), { weekday: "long", day: "numeric", month: "long" });
  return fr ? label.charAt(0).toUpperCase() + label.slice(1) : label;
}

export function greeting(date = new Date()): string {
  const fr = getLang() === "fr";
  const hour = date.getHours();
  if (hour < 5 || hour >= 18) return fr ? "Bonsoir" : "Good evening";
  if (hour < 12) return fr ? "Bonjour" : "Good morning";
  return fr ? "Bon après-midi" : "Good afternoon";
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds % 60)} s`;
}

const CLASSIFICATION_LABELS = {
  en: ["C0 · Public", "C1 · Internal", "C2 · Confidential", "C3 · Secret"],
  fr: ["C0 · Public", "C1 · Interne", "C2 · Confidentiel", "C3 · Secret"],
} as const;

export function classificationLabel(level: number): string {
  return CLASSIFICATION_LABELS[getLang()][level] ?? `C${level}`;
}

/** @deprecated use classificationLabel (localized) */
export const CLASSIFICATION = CLASSIFICATION_LABELS.en;
