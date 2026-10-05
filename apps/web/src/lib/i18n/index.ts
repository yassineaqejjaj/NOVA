"use client";

import { useSyncExternalStore } from "react";

import { useUi } from "@/stores/ui";

/**
 * Minimal, typed i18n. Each feature defines its own messages next to its code with `defineMessages`;
 * the French table must cover every English key (checked by TypeScript).
 *
 *   const M = defineMessages({ en: { hello: "Hello {name}" }, fr: { hello: "Bonjour {name}" } });
 *   const t = useT(M);  t("hello", { name })
 *
 * A message is a string with {placeholders}, or a function of the variables (plurals, grammar).
 */
export type Lang = "en" | "fr";
export const LANGS: { value: Lang; label: string }[] = [
  { value: "en", label: "English" },
  { value: "fr", label: "Français" },
];

type Vars = Record<string, string | number | null | undefined>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- message functions take arbitrary variables
type Message = string | ((vars: any) => string);
export type Messages<T extends Record<string, Message>> = { en: T; fr: { [K in keyof T]: Message } };

export function defineMessages<T extends Record<string, Message>>(messages: Messages<T>): Messages<T> {
  return messages;
}

export function browserLang(): Lang {
  if (typeof navigator === "undefined") return "en";
  return navigator.language.toLowerCase().startsWith("fr") ? "fr" : "en";
}

/** The interface language: the user's preference, else the browser's. */
export function getLang(): Lang {
  return useUi.getState().lang ?? browserLang();
}

const serverLang = (): Lang => "en";

/** Reactive interface language. Server render uses English; the client switches right after hydration. */
export function useLang(): Lang {
  return useSyncExternalStore(useUi.subscribe, getLang, serverLang);
}

export function format(message: Message, vars?: Vars): string {
  if (typeof message === "function") return message(vars ?? {});
  if (!vars) return message;
  return message.replace(/\{(\w+)\}/g, (_, key: string) => (vars[key] === undefined || vars[key] === null ? "" : String(vars[key])));
}

export function translate<T extends Record<string, Message>>(messages: Messages<T>, lang: Lang, key: keyof T & string, vars?: Vars): string {
  const table = messages[lang] as Record<string, Message>;
  return format(table[key] ?? (messages.en as Record<string, Message>)[key] ?? key, vars);
}

export function useT<T extends Record<string, Message>>(messages: Messages<T>) {
  const lang = useLang();
  return (key: keyof T & string, vars?: Vars) => translate(messages, lang, key, vars);
}

/** "1 task" / "2 tasks" — `forms` per language: [one, other]. */
export function plural(n: number, one: string, other: string): string {
  return `${n} ${n === 1 || (getLang() === "fr" && n === 0) ? one : other}`;
}
