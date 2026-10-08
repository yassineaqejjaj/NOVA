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

export function LanguageSwitch({ className, tone = "dark" }: { className?: string; tone?: "dark" | "light" }) {
  const lang = useLang();
  const t = useT(M);
  const setLang = useUi((s) => s.setLang);
  const light = tone === "light";
  return (
    <div
      role="radiogroup"
      aria-label={t("language")}
      className={cn(
        "flex items-center gap-0.5 rounded-full border font-medium",
        light ? "border-border bg-surface p-1 text-[13px] shadow-[0_4px_14px_-8px_rgb(30_20_18/0.25)]" : "border-white/10 bg-white/5 p-0.5 text-[11.5px]",
        className,
      )}
    >
      {LANGS.map((l) => {
        const active = lang === l.value;
        return (
          <button
            key={l.value}
            role="radio"
            aria-checked={active}
            onClick={() => setLang(l.value as Lang)}
            className={cn(
              "rounded-full uppercase tracking-wide transition-colors",
              light ? "px-3.5 py-1.5" : "px-2.5 py-1",
              light
                ? active ? "bg-accent-soft text-accent" : "text-muted hover:text-text"
                : active ? "bg-white/90 text-black" : "text-current opacity-70 hover:opacity-100",
            )}
          >
            {l.value}
          </button>
        );
      })}
    </div>
  );
}

/** Auth screens: the cosmic hero (always dark) and the form card on the right (follows the theme). */
export function AuthShell({ children }: { children: React.ReactNode }) {
  const t = useT(M);
  return (
    <div className="flex min-h-dvh flex-col bg-background font-[family-name:var(--font-dm-sans)] text-text lg:flex-row">
      <aside className="relative isolate flex shrink-0 flex-col overflow-hidden bg-[#07020a] px-6 pb-7 pt-6 text-white lg:min-h-dvh lg:w-[52%] lg:px-[3.75rem] lg:pb-14 lg:pt-14">
        <Nebula />
        <div className="flex items-center justify-between">
          <NovaLogo height={52} className="h-9 w-auto lg:h-[52px]" />
          <LanguageSwitch className="lg:hidden" />
        </div>
        <div className="relative hidden flex-1 place-items-center lg:grid">
          <HeroOrb />
        </div>
        <div className="mt-6 flex items-end justify-between gap-6 lg:mt-0">
          <div className="max-w-[420px]">
            <h1 className="whitespace-pre-line text-[28px] font-normal leading-[1.12] tracking-tight lg:text-[44px]">{t("heroTitle")}</h1>
            <p className="mt-3 text-[14px] leading-relaxed text-white/80 lg:mt-4 lg:text-[17px]">{t("heroText")}</p>
          </div>
          <p className="hidden shrink-0 whitespace-pre-line text-right text-[15px] leading-snug text-white/85 lg:block">{t("footerTagline")}</p>
        </div>
      </aside>
      <main className="relative flex flex-1 flex-col px-4 py-8 sm:px-8 lg:py-10">
        <div className="absolute right-6 top-6 hidden lg:block lg:right-9 lg:top-9">
          <LanguageSwitch tone="light" />
        </div>
        <div className="mx-auto flex w-full max-w-[512px] flex-1 flex-col justify-center">{children}</div>
      </main>
    </div>
  );
}

/** NOVA's orb over the nebula, with the glowing orbit that crosses in front of it. */
function HeroOrb() {
  const reduce = useReducedMotion();
  return (
    <div className="relative aspect-square w-[min(76%,600px)]" aria-hidden>
      <div className="absolute -inset-[18%] rounded-full bg-[radial-gradient(circle,rgb(255_120_150/0.45),rgb(248_72_94/0.18)_45%,transparent_70%)] blur-2xl" />
      <Orbit side="back" />
      <motion.img
        src="/brand/nova-orb-hero.webp"
        alt=""
        draggable={false}
        className="relative size-full select-none drop-shadow-[0_0_40px_rgb(255_140_170/0.55)]"
        animate={reduce ? undefined : { y: [0, -8, 0], rotate: [0, 1.5, 0] }}
        transition={{ duration: 9, repeat: Infinity, ease: "easeInOut" }}
      />
      <Orbit side="front" />
    </div>
  );
}

/** Two tilted rings, split in a back half (behind the orb) and a front half. */
function Orbit({ side }: { side: "back" | "front" }) {
  const id = useId();
  const front = side === "front";
  // Unit square of the orb (100×100); the rings overflow it on both sides.
  const rings = [
    { rx: 74, ry: 19, tilt: 22, width: 1.25, opacity: 1 },
    { rx: 66, ry: 14, tilt: 28, width: 0.5, opacity: 0.7 },
  ];
  return (
    <svg className="pointer-events-none absolute inset-0 size-full overflow-visible" viewBox="0 0 100 100">
      <defs>
        <linearGradient id={`${id}-ring`} x1="0" x2="1">
          <stop offset="0" stopColor="#ff9fb8" stopOpacity="0.15" />
          <stop offset="0.35" stopColor="#ffe3ea" stopOpacity="0.95" />
          <stop offset="0.7" stopColor="#ff7ab8" stopOpacity="0.85" />
          <stop offset="1" stopColor="#c86bff" stopOpacity="0.3" />
        </linearGradient>
        <filter id={`${id}-glow`} x="-20%" y="-50%" width="140%" height="200%">
          <feGaussianBlur stdDeviation="1.1" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {rings.map((r, i) => (
        <path
          key={i}
          // the upper arc passes behind the orb, the lower arc in front of it
          d={front ? `M ${50 + r.rx} 50 A ${r.rx} ${r.ry} 0 0 1 ${50 - r.rx} 50` : `M ${50 - r.rx} 50 A ${r.rx} ${r.ry} 0 0 1 ${50 + r.rx} 50`}
          transform={`rotate(${r.tilt} 50 50)`}
          fill="none"
          stroke={`url(#${id}-ring)`}
          strokeWidth={r.width}
          strokeLinecap="round"
          opacity={front ? r.opacity : r.opacity * 0.55}
          filter={`url(#${id}-glow)`}
        />
      ))}
    </svg>
  );
}

/** The nebula: crimson and violet clouds (fractal noise shaped by gradients), stars and two far galaxies. */
function Nebula() {
  const id = useId();
  // Deterministic sky (no hydration mismatch): golden-angle spread, a few bright stars.
  const stars = Array.from({ length: 150 }, (_, i) => ({
    x: (i * 61.803) % 100,
    y: (i * 38.197 + (i % 7) * 9.1) % 100,
    r: i % 17 === 0 ? 1.5 : i % 5 === 0 ? 0.9 : 0.5,
    o: 0.25 + ((i * 29) % 70) / 100,
  }));
  return (
    <div className="absolute inset-0 -z-10" aria-hidden>
      <div className="absolute inset-0 bg-[radial-gradient(7%_5%_at_85%_9%,rgb(255_236_210/0.95),transparent_75%),radial-gradient(18%_12%_at_84%_10%,rgb(255_120_100/0.75),transparent_72%),radial-gradient(34%_24%_at_80%_14%,rgb(235_45_105/0.7),transparent_72%),radial-gradient(52%_36%_at_70%_17%,rgb(150_40_165/0.6),transparent_72%),radial-gradient(60%_22%_at_40%_3%,rgb(95_35_140/0.55),transparent_72%),radial-gradient(30%_40%_at_0%_42%,rgb(238_36_78/0.9),transparent_72%),radial-gradient(26%_22%_at_5%_61%,rgb(140_52_195/0.62),transparent_72%),radial-gradient(46%_30%_at_12%_83%,rgb(205_24_62/0.85),transparent_72%),radial-gradient(48%_32%_at_90%_87%,rgb(228_30_72/0.8),transparent_72%),radial-gradient(28%_24%_at_99%_58%,rgb(150_50_185/0.5),transparent_72%)]" />
      {/* bright crimson cloud banks at the edges */}
      <svg className="absolute inset-0 size-full mix-blend-screen">
        <filter id={`${id}-clouds`}>
          <feTurbulence type="fractalNoise" baseFrequency="0.0042 0.0065" numOctaves="5" seed="7" />
          <feColorMatrix values="0 0 0 0 1  0 0 0 0 0.13  0 0 0 0 0.28  0 0 0 4.2 -2.15" />
        </filter>
        <radialGradient id={`${id}-vignette`} cx="50%" cy="44%" r="72%">
          <stop offset="0.3" stopColor="black" />
          <stop offset="0.8" stopColor="white" />
        </radialGradient>
        <mask id={`${id}-edges`}>
          <rect width="100%" height="100%" fill={`url(#${id}-vignette)`} />
        </mask>
        <rect width="100%" height="100%" filter={`url(#${id}-clouds)`} mask={`url(#${id}-edges)`} />
      </svg>
      {/* dark violet shadows inside the clouds: depth instead of haze */}
      <svg className="absolute inset-0 size-full mix-blend-multiply">
        <filter id={`${id}-shadows`}>
          <feTurbulence type="fractalNoise" baseFrequency="0.006 0.009" numOctaves="4" seed="23" />
          <feColorMatrix values="0 0 0 0 0.12  0 0 0 0 0.02  0 0 0 0 0.16  0 0 0 3.6 -1.6" />
        </filter>
        <rect width="100%" height="100%" filter={`url(#${id}-shadows)`} />
      </svg>
      <svg className="absolute inset-0 size-full">
        <defs>
          <radialGradient id={`${id}-galaxy`}>
            <stop offset="0" stopColor="#fff4e8" stopOpacity="0.95" />
            <stop offset="0.25" stopColor="#ffb3c8" stopOpacity="0.55" />
            <stop offset="1" stopColor="#9b5cff" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx="27%" cy="20%" rx="34" ry="11" fill={`url(#${id}-galaxy)`} transform="rotate(-24)" style={{ transformBox: "fill-box", transformOrigin: "center" }} />
        <ellipse cx="87%" cy="72%" rx="38" ry="12" fill={`url(#${id}-galaxy)`} transform="rotate(-30)" style={{ transformBox: "fill-box", transformOrigin: "center" }} />
        {stars.map((star, i) => (
          <circle key={i} cx={`${star.x}%`} cy={`${star.y}%`} r={star.r} fill={i % 9 === 0 ? "#ffd6e0" : "white"} opacity={star.o} />
        ))}
      </svg>
      {/* keeps the title readable over the clouds */}
      <div className="absolute inset-x-0 bottom-0 h-[45%] bg-[linear-gradient(to_top,rgb(7_2_10/0.88),rgb(7_2_10/0.35)_55%,transparent)]" />
    </div>
  );
}

export function Tabs({ value, onChange, items }: { value: string; onChange: (v: string) => void; items: { value: string; label: string }[] }) {
  return (
    <div role="tablist" className="grid grid-cols-2">
      {items.map((item) => (
        <button
          key={item.value}
          role="tab"
          aria-selected={value === item.value}
          onClick={() => onChange(item.value)}
          className={cn("relative pb-3.5 pt-1 text-[16px] transition-colors", value === item.value ? "font-semibold text-text" : "font-medium text-muted hover:text-text")}
        >
          {item.label}
          {value === item.value ? <motion.span layoutId="auth-tab" className="absolute inset-x-0 bottom-0 h-[2px] rounded-full bg-accent" /> : null}
        </button>
      ))}
    </div>
  );
}

/** Outlined field: leading icon, label set on the top border (as in NOVA's sign-in design). */
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
      <div
        className={cn(
          "relative flex h-[52px] items-center gap-3 rounded-[10px] border border-border-strong bg-surface px-3.5 transition-colors focus-within:border-accent/60 focus-within:ring-2 focus-within:ring-accent/15",
          input.readOnly && "bg-surface-2/60",
        )}
      >
        <label htmlFor={id} className="absolute -top-[9px] left-3 rounded-sm bg-surface px-1.5 text-[12.5px] leading-[18px] text-muted">
          {label}
        </label>
        <Icon className="size-[19px] shrink-0 text-muted" strokeWidth={1.6} />
        <input id={id} className="block h-full w-full min-w-0 bg-transparent text-[15px] text-text outline-none placeholder:text-subtle read-only:text-muted" {...input} />
        {trailing}
      </div>
      {hint ? <p className="mt-1.5 px-1 text-[11.5px] text-subtle">{hint}</p> : null}
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
