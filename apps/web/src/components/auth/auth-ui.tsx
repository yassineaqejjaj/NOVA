"use client";

import { cn } from "@nova/ui";
import { motion, useReducedMotion } from "framer-motion";
import { Check, Eye, EyeOff, type LucideIcon } from "lucide-react";
import { useId, useRef, useState } from "react";

import { NovaLogo } from "@/components/shell/nova-mark";
import { NovaOrb } from "@/components/shell/nova-orb";
import { type Lang, LANGS, useLang, useT } from "@/lib/i18n";
import { useUi } from "@/stores/ui";

import { M } from "./auth.messages";

/** NOVA's planet: the living orb with a tilted orbit and a spark travelling on it. */
export function Planet({ size = 260, className }: { size?: number; className?: string }) {
  const reduce = useReducedMotion();
  const w = size * 1.9;
  const h = size * 0.62;
  return (
    <div className={cn("relative grid place-items-center", className)} style={{ width: w, height: size * 1.15 }} aria-hidden>
      <div className="absolute rounded-full bg-[radial-gradient(circle,rgb(248_72_94/0.38),transparent_65%)] blur-2xl" style={{ width: size * 1.5, height: size * 1.5 }} />
      <svg className="absolute" width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ transform: "rotate(-14deg)" }}>
        <defs>
          <linearGradient id="nova-ring" x1="0" x2="1">
            <stop offset="0" stopColor="#f8485e" stopOpacity="0.05" />
            <stop offset="0.45" stopColor="#ff8c9a" stopOpacity="0.9" />
            <stop offset="1" stopColor="#f8485e" stopOpacity="0.15" />
          </linearGradient>
        </defs>
        {/* back half of the ring, behind the planet */}
        <path d={`M 4 ${h / 2} A ${w / 2 - 4} ${h / 2 - 4} 0 0 1 ${w - 4} ${h / 2}`} fill="none" stroke="url(#nova-ring)" strokeWidth="1.2" opacity="0.55" />
      </svg>
      <NovaOrb state="idle" size={size} className="relative" />
      <svg className="pointer-events-none absolute" width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ transform: "rotate(-14deg)" }}>
        <path id="nova-front" d={`M ${w - 4} ${h / 2} A ${w / 2 - 4} ${h / 2 - 4} 0 0 1 4 ${h / 2}`} fill="none" stroke="url(#nova-ring)" strokeWidth="1.6" />
        {!reduce ? (
          <circle r="3" fill="#ffd1d7">
            <animateMotion dur="9s" repeatCount="indefinite" path={`M 4 ${h / 2} A ${w / 2 - 4} ${h / 2 - 4} 0 1 1 ${w - 4} ${h / 2} A ${w / 2 - 4} ${h / 2 - 4} 0 1 1 4 ${h / 2}`} />
            <animate attributeName="opacity" values="0.2;1;0.2" dur="9s" repeatCount="indefinite" />
          </circle>
        ) : null}
      </svg>
    </div>
  );
}

export function LanguageSwitch({ className }: { className?: string }) {
  const lang = useLang();
  const t = useT(M);
  const setLang = useUi((s) => s.setLang);
  return (
    <div role="radiogroup" aria-label={t("language")} className={cn("flex items-center gap-0.5 rounded-full border border-white/10 bg-white/5 p-0.5 text-[11.5px] font-medium", className)}>
      {LANGS.map((l) => (
        <button
          key={l.value}
          role="radio"
          aria-checked={lang === l.value}
          onClick={() => setLang(l.value as Lang)}
          className={cn("rounded-full px-2.5 py-1 uppercase tracking-wide transition-colors", lang === l.value ? "bg-white/90 text-black" : "text-current opacity-70 hover:opacity-100")}
        >
          {l.value}
        </button>
      ))}
    </div>
  );
}

/** Auth screens: a cosmic hero (always dark) and the form panel (follows the theme). */
export function AuthShell({ children }: { children: React.ReactNode }) {
  const t = useT(M);
  return (
    <div className="flex min-h-dvh flex-col bg-background font-[family-name:var(--font-montserrat)] text-text lg:flex-row">
      <aside className="relative isolate flex shrink-0 flex-col overflow-hidden bg-[#07070b] px-6 pb-8 pt-6 text-white lg:min-h-dvh lg:w-[46%] lg:px-12 lg:pb-10 lg:pt-10">
        <div className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_30%_20%,rgb(248_72_94/0.22),transparent_55%),radial-gradient(ellipse_at_80%_110%,rgb(248_72_94/0.18),transparent_50%)]" />
        <Stars />
        <div className="flex items-center justify-between">
          <NovaLogo height={26} className="brightness-0 invert" />
          <LanguageSwitch className="lg:hidden" />
        </div>
        <div className="mx-auto mt-6 hidden lg:mt-16 lg:block">
          <Planet size={240} />
        </div>
        <div className="mt-4 max-w-md lg:mt-auto">
          <h1 className="whitespace-pre-line text-[28px] font-medium leading-[1.12] tracking-tight lg:text-[44px]">{t("heroTitle")}</h1>
          <p className="mt-3 text-[14px] leading-relaxed text-white/65 lg:text-[16px]">{t("heroText")}</p>
        </div>
        <div className="mt-8 hidden items-end justify-between text-[11.5px] text-white/50 lg:flex">
          <div>
            <NovaLogo height={14} className="brightness-0 invert opacity-80" />
            <div className="mt-1">{t("poweredBy")}</div>
          </div>
          <div className="whitespace-pre-line text-right">{t("footerTagline")}</div>
        </div>
      </aside>
      <main className="relative flex flex-1 flex-col px-4 py-8 sm:px-8 lg:py-10">
        <div className="absolute right-6 top-6 hidden lg:block">
          <LanguageSwitch className="border-border bg-surface-2 text-text [&_[aria-checked=true]]:bg-text [&_[aria-checked=true]]:text-background" />
        </div>
        <div className="mx-auto flex w-full max-w-[440px] flex-1 flex-col justify-center">{children}</div>
      </main>
    </div>
  );
}

function Stars() {
  // Deterministic sky (no hydration mismatch).
  const stars = Array.from({ length: 46 }, (_, i) => ({ x: (i * 37) % 100, y: (i * 61) % 100, s: (i % 3) + 1, o: 0.15 + ((i * 13) % 50) / 100 }));
  return (
    <svg className="absolute inset-0 -z-10 h-full w-full" aria-hidden>
      {stars.map((star, i) => <circle key={i} cx={`${star.x}%`} cy={`${star.y}%`} r={star.s * 0.45} fill="white" opacity={star.o} />)}
    </svg>
  );
}

export function Tabs({ value, onChange, items }: { value: string; onChange: (v: string) => void; items: { value: string; label: string }[] }) {
  return (
    <div role="tablist" className="grid grid-cols-2 border-b border-border">
      {items.map((item) => (
        <button
          key={item.value}
          role="tab"
          aria-selected={value === item.value}
          onClick={() => onChange(item.value)}
          className={cn("relative pb-3 pt-1 text-[14px] transition-colors", value === item.value ? "font-medium text-text" : "text-muted hover:text-text")}
        >
          {item.label}
          {value === item.value ? <motion.span layoutId="auth-tab" className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent" /> : null}
        </button>
      ))}
    </div>
  );
}

/** Field with a leading icon and its label inside the box (as in NOVA's sign-in design). */
export function Field({
  icon: Icon,
  label,
  hint,
  trailing,
  className,
  ...input
}: { icon: LucideIcon; label: string; hint?: string; trailing?: React.ReactNode } & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className={className}>
      <label
        htmlFor={id}
        className={cn(
          "flex items-center gap-3 rounded-[12px] border border-border bg-surface px-3.5 py-2 transition-colors focus-within:border-accent/60 focus-within:ring-2 focus-within:ring-accent/15",
          input.readOnly && "bg-surface-2/60",
        )}
      >
        <Icon className="size-[18px] shrink-0 text-subtle" strokeWidth={1.6} />
        <span className="min-w-0 flex-1">
          <span className="block text-[11.5px] text-subtle">{label}</span>
          <input id={id} aria-label={label} className="block w-full bg-transparent text-[14.5px] text-text outline-none placeholder:text-subtle/60 read-only:text-muted" {...input} />
        </span>
        {trailing}
      </label>
      {hint ? <p className="mt-1 px-1 text-[11.5px] text-subtle">{hint}</p> : null}
    </div>
  );
}

export function PasswordField({ icon, label, value, onChange, autoComplete, ...rest }: { icon: LucideIcon; label: string; value: string; onChange: (v: string) => void; autoComplete: string } & Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value">) {
  const t = useT(M);
  const [visible, setVisible] = useState(false);
  return (
    <Field
      icon={icon}
      label={label}
      type={visible ? "text" : "password"}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      autoComplete={autoComplete}
      required
      trailing={
        <button type="button" onClick={() => setVisible(!visible)} className="rounded-md p-1 text-subtle hover:text-text" aria-label={visible ? t("hidePassword") : t("showPassword")}>
          {visible ? <EyeOff className="size-[18px]" strokeWidth={1.6} /> : <Eye className="size-[18px]" strokeWidth={1.6} />}
        </button>
      }
      {...rest}
    />
  );
}

export function passwordRules(password: string) {
  return { length: password.length >= 12, letters: /\p{L}/u.test(password), digits: /\d/.test(password) };
}

export function PasswordRules({ password }: { password: string }) {
  const t = useT(M);
  const rules = passwordRules(password);
  const items: [keyof typeof rules, string][] = [["length", t("ruleLength")], ["letters", t("ruleLetters")], ["digits", t("ruleDigits")]];
  return (
    <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 px-1 text-[11.5px]" aria-live="polite">
      {items.map(([key, label]) => (
        <li key={key} className={cn("inline-flex items-center gap-1", rules[key] ? "text-success" : "text-subtle")}>
          <Check className={cn("size-3", !rules[key] && "opacity-40")} /> {label}
        </li>
      ))}
    </ul>
  );
}

export function Checkbox({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-[13px] text-muted">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
      <span aria-hidden className={cn("mt-px grid size-[18px] shrink-0 place-items-center rounded-[5px] border transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-accent/40", checked ? "border-accent bg-accent text-white" : "border-border-strong bg-surface")}>
        {checked ? <Check className="size-3" strokeWidth={3} /> : null}
      </span>
      <span>{children}</span>
    </label>
  );
}

/** Six boxes for the e-mailed code; paste-friendly. */
export function CodeInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const t = useT(M);
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const digits = Array.from({ length: 6 }, (_, i) => value[i] ?? "");
  const set = (i: number, digit: string) => {
    const next = [...digits];
    next[i] = digit;
    onChange(next.join("").slice(0, 6));
  };
  return (
    <div className="flex justify-between gap-2" role="group" aria-label={t("code")}>
      {digits.map((digit, i) => (
        <input
          key={i}
          ref={(el) => { refs.current[i] = el; }}
          value={digit}
          inputMode="numeric"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          aria-label={t("codeDigit", { n: i + 1 })}
          onChange={(e) => {
            const v = e.target.value.replace(/\D/g, "");
            if (v.length > 1) {
              onChange(v.slice(0, 6));
              refs.current[Math.min(v.length, 5)]?.focus();
              return;
            }
            set(i, v);
            if (v && i < 5) refs.current[i + 1]?.focus();
          }}
          onKeyDown={(e) => {
            if (e.key === "Backspace" && !digit && i > 0) refs.current[i - 1]?.focus();
          }}
          onPaste={(e) => {
            const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
            if (pasted) {
              e.preventDefault();
              onChange(pasted);
              refs.current[Math.min(pasted.length, 5)]?.focus();
            }
          }}
          className="h-14 w-full min-w-0 rounded-[12px] border border-border bg-surface text-center text-[22px] font-semibold tabular-nums text-text outline-none transition-colors focus:border-accent/60 focus:ring-2 focus:ring-accent/15"
        />
      ))}
    </div>
  );
}

export function GoogleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.4h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.7Z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24Z" />
      <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6h-4a12 12 0 0 0 0 10.8l4-3.1Z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9Z" />
    </svg>
  );
}
