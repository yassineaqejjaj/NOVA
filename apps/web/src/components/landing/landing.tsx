"use client";

import { cn } from "@nova/ui";
import { motion } from "framer-motion";
import {
  ArrowRight,
  BookOpenCheck,
  Bot,
  Eye,
  FileStack,
  Fingerprint,
  Gauge,
  KeyRound,
  Layers3,
  Lock,
  Menu,
  Moon,
  Network,
  Orbit,
  Rocket,
  ScrollText,
  ServerCog,
  ShieldCheck,
  Sparkles,
  Sun,
  Target,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useLang as useAppLang } from "@/lib/i18n";
import { useUi } from "@/stores/ui";

import { COPY, type Lang } from "./copy";

const DEMO_EMAIL = process.env.NEXT_PUBLIC_DEMO_EMAIL ?? "yassine.aqejjaj@devoteam.com";

function demoHref(subject: string): string {
  return process.env.NEXT_PUBLIC_DEMO_URL ?? `mailto:${DEMO_EMAIL}?subject=${encodeURIComponent(subject)}`;
}

/** Same language preference as the app (persisted, applied after sign-in too). */
function useLang(): [Lang, (lang: Lang) => void] {
  const lang = useAppLang();
  const setLang = useUi((s) => s.setLang);
  return [lang, setLang];
}

function Brand() {
  return (
    <Link href="/landing" className="flex items-center gap-3" aria-label="devoteam · NOVA">
      {/* eslint-disable-next-line @next/next/no-img-element -- static brand assets */}
      <img src="/brand/devoteam.png" alt="devoteam" width={100} height={30} className="h-[26px] w-auto dark:hidden" />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/brand/devoteam-dark.png" alt="devoteam" width={100} height={30} className="hidden h-[26px] w-auto dark:block" />
      <span className="h-5 w-px bg-border-strong" />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/brand/nova-wordmark.png" alt="NOVA" width={70} height={19} className="h-[17px] w-auto dark:brightness-[1.35]" />
    </Link>
  );
}

function Segmented({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div role="group" aria-label={label} className="flex items-center gap-0.5 rounded-full border border-border bg-surface p-1">
      {children}
    </div>
  );
}

function SegmentButton({ active, onClick, children, label }: { active: boolean; onClick: () => void; children: React.ReactNode; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      className={cn(
        "flex h-8 min-w-8 items-center justify-center rounded-full px-2 text-[13px] font-semibold transition-colors [&_svg]:size-4",
        active ? "bg-text text-background" : "text-muted hover:text-text",
      )}
    >
      {children}
    </button>
  );
}

function Header({ lang, setLang }: { lang: Lang; setLang: (l: Lang) => void }) {
  const t = COPY[lang];
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const [open, setOpen] = useState(false);
  const links = [
    { href: "#vision", label: t.nav.vision },
    { href: "#produit", label: t.nav.product },
    { href: "#cas-usage", label: t.nav.useCases },
    { href: "#securite", label: t.nav.security },
  ];
  const controls = (
    <>
      <Segmented label="Theme">
        <SegmentButton active={theme === "light"} onClick={() => setTheme("light")} label={t.theme.light}><Sun /></SegmentButton>
        <SegmentButton active={theme === "dark"} onClick={() => setTheme("dark")} label={t.theme.dark}><Moon /></SegmentButton>
      </Segmented>
      <Segmented label="Language">
        <SegmentButton active={lang === "fr"} onClick={() => setLang("fr")} label="Français">FR</SegmentButton>
        <SegmentButton active={lang === "en"} onClick={() => setLang("en")} label="English">EN</SegmentButton>
      </Segmented>
    </>
  );
  return (
    <header className="sticky top-3 z-40 mx-auto w-full max-w-[1240px] px-4">
      <div className="flex items-center gap-4 rounded-full border border-border bg-surface/85 py-2.5 pl-6 pr-2.5 shadow-[0_8px_30px_rgb(0_0_0/0.04)] backdrop-blur-xl">
        <Brand />
        <nav className="mx-auto hidden items-center gap-8 lg:flex" aria-label="Sections">
          {links.map((l) => (
            <a key={l.href} href={l.href} className="text-[15px] font-medium text-text/80 transition-colors hover:text-text">{l.label}</a>
          ))}
        </nav>
        <div className="ml-auto hidden items-center gap-3 lg:ml-0 lg:flex">
          {controls}
          <Link href="/login" className="px-3 text-[15px] font-medium text-text/80 hover:text-text">{t.signIn}</Link>
          <a href={demoHref(t.demoSubject)} className="rounded-full bg-[var(--brand)] px-6 py-3 text-[15px] font-semibold text-white shadow-[0_10px_30px_-10px_var(--brand)] transition-transform hover:-translate-y-0.5">
            {t.bookDemo}
          </a>
        </div>
        <button className="ml-auto flex size-10 items-center justify-center rounded-full border border-border lg:hidden" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={t.menu}>
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </div>
      {open ? (
        <div className="mt-2 space-y-4 rounded-[24px] border border-border bg-surface p-5 shadow-panel lg:hidden">
          <nav className="flex flex-col gap-3" aria-label="Sections">
            {links.map((l) => (
              <a key={l.href} href={l.href} onClick={() => setOpen(false)} className="text-[16px] font-medium">{l.label}</a>
            ))}
          </nav>
          <div className="flex flex-wrap items-center gap-3">{controls}</div>
          <div className="flex flex-col gap-2">
            <Link href="/login" className="rounded-full border border-border py-3 text-center text-[15px] font-medium">{t.signIn}</Link>
            <a href={demoHref(t.demoSubject)} className="rounded-full bg-[var(--brand)] py-3 text-center text-[15px] font-semibold text-white">{t.bookDemo}</a>
          </div>
        </div>
      ) : null}
    </header>
  );
}

const AGENT_STYLE = [
  { icon: Target, tone: "bg-[#5cc49a]", pos: "lg:left-[2%] lg:top-[6%]" },
  { icon: Sparkles, tone: "bg-[#f2b63c]", pos: "lg:right-[0%] lg:top-[8%]" },
  { icon: Wrench, tone: "bg-[#6aa7f5]", pos: "lg:left-[6%] lg:bottom-[12%]" },
  { icon: Gauge, tone: "bg-[var(--brand)]", pos: "lg:right-[3%] lg:bottom-[10%]" },
];

function AgentCard({ index, name, role }: { index: number; name: string; role: string }) {
  const style = AGENT_STYLE[index]!;
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: [0, -6, 0] }}
      transition={{ opacity: { delay: 0.2 + index * 0.1 }, y: { duration: 6, repeat: Infinity, ease: "easeInOut", delay: index * 0.8 } }}
      className={cn("rounded-[22px] border border-border bg-surface/95 p-5 shadow-[0_18px_50px_-24px_rgb(0_0_0/0.25)] backdrop-blur lg:absolute lg:w-[196px]", style.pos)}
    >
      <div className="flex items-center gap-2.5">
        <span className={cn("flex size-10 items-center justify-center rounded-full text-white [&_svg]:size-5", style.tone)}><style.icon /></span>
        <span className="size-2 rounded-full bg-[#5cc49a]" aria-hidden />
      </div>
      <div className="mt-4 text-[16px] font-bold">{name}</div>
      <div className="mt-1 text-[13px] text-muted">{role}</div>
    </motion.div>
  );
}

function OrbitDiagram({ lang }: { lang: Lang }) {
  const t = COPY[lang].hero;
  return (
    <div className="relative">
      <div className="relative mx-auto grid max-w-[620px] grid-cols-2 gap-4 lg:block lg:aspect-square">
        {/* orbits */}
        <div aria-hidden className="pointer-events-none absolute inset-[8%] hidden rounded-full border border-[var(--brand)]/25 lg:block" />
        <div aria-hidden className="pointer-events-none absolute inset-[22%] hidden rounded-full border border-dashed border-[var(--brand)]/25 lg:block" />
        <div className="col-span-2 flex justify-center lg:absolute lg:inset-0 lg:items-center">
          <motion.div
            initial={{ scale: 0.92, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.5 }}
            className="relative flex size-[220px] flex-col items-center justify-center rounded-full bg-surface text-center shadow-[0_0_0_10px_var(--brand-soft),0_30px_80px_-20px_var(--brand-glow)]"
          >
            <div aria-hidden className="absolute inset-3 rounded-full border border-[var(--brand)]/20" />
            <span className="flex size-16 items-center justify-center rounded-[18px] bg-[var(--brand)] text-white shadow-[0_12px_30px_-8px_var(--brand)]">
              <Network className="size-8" />
            </span>
            <span className="mt-4 font-display text-[26px] font-bold tracking-tight">NOVA</span>
            <span className="text-[13px] text-muted">{t.hub}</span>
          </motion.div>
        </div>
        {t.agents.map((a, i) => <AgentCard key={a.name} index={i} name={a.name} role={a.role} />)}
      </div>
      <div className="mt-6 flex justify-center lg:-mt-2">
        <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-2 text-[14px] text-text/80">
          <Zap className="size-4 text-[var(--brand)]" /> {t.synced}
        </span>
      </div>
    </div>
  );
}

const CHIP_DOTS = ["bg-[#5cc49a]", "bg-[var(--brand)]", "bg-[#f2b63c]", "bg-[#6aa7f5]"];

function Hero({ lang }: { lang: Lang }) {
  const t = COPY[lang];
  return (
    <section className="relative mx-auto grid w-full max-w-[1240px] items-center gap-14 px-6 pb-24 pt-20 lg:grid-cols-[1.05fr_1fr] lg:pt-28">
      <div>
        <motion.p initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex items-center gap-2 text-[14px] font-semibold uppercase tracking-wide text-[var(--brand)]">
          <span className="size-1.5 rounded-full bg-[var(--brand)]" /> {t.hero.eyebrow}
        </motion.p>
        <motion.h1
          key={lang}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mt-5 font-display text-[38px] font-bold leading-[1.04] tracking-[-0.02em] text-text/90 sm:text-[60px] lg:text-[76px]"
        >
          {t.hero.title}
        </motion.h1>
        <p className="mt-7 max-w-[640px] text-[18px] leading-relaxed text-muted sm:text-[20px]">{t.hero.subtitle}</p>
        <div className="mt-9 flex flex-wrap gap-3">
          <a href="#produit" className="inline-flex items-center gap-2 rounded-full bg-[var(--brand)] px-8 py-4 text-[17px] font-semibold text-white shadow-[0_14px_34px_-12px_var(--brand)] transition-transform hover:-translate-y-0.5">
            {t.discover} <ArrowRight className="size-4" />
          </a>
          <a href={demoHref(t.demoSubject)} className="inline-flex items-center rounded-full border border-border-strong bg-surface px-8 py-4 text-[17px] font-semibold transition-colors hover:border-text/40">
            {t.bookDemo}
          </a>
        </div>
        <ul className="mt-12 flex flex-wrap gap-2.5">
          {t.hero.chips.map((chip, i) => (
            <li key={chip} className="flex items-center gap-2 rounded-[16px] border border-border bg-surface px-3.5 py-2.5 text-[13.5px] text-text/80">
              <span className={cn("size-2 rounded-full", CHIP_DOTS[i])} /> {chip}
            </li>
          ))}
        </ul>
      </div>
      <OrbitDiagram lang={lang} />
    </section>
  );
}

function SectionHead({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle?: string }) {
  return (
    <div className="mx-auto max-w-[760px] text-center">
      <p className="text-[13px] font-semibold uppercase tracking-[0.14em] text-[var(--brand)]">{eyebrow}</p>
      <h2 className="mt-4 font-display text-[32px] font-bold leading-tight tracking-[-0.01em] sm:text-[44px]">{title}</h2>
      {subtitle ? <p className="mt-4 text-[17px] leading-relaxed text-muted">{subtitle}</p> : null}
    </div>
  );
}

const PILLAR_ICONS = [Bot, Orbit, Rocket];

function Vision({ lang }: { lang: Lang }) {
  const t = COPY[lang].vision;
  return (
    <section id="vision" className="scroll-mt-28 px-6 py-24">
      <SectionHead eyebrow={t.eyebrow} title={t.title} subtitle={t.subtitle} />
      <div className="mx-auto mt-14 grid max-w-[1120px] gap-5 md:grid-cols-3">
        {t.pillars.map((p, i) => {
          const Icon = PILLAR_ICONS[i]!;
          return (
            <motion.article
              key={p.name}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ delay: i * 0.08 }}
              className={cn("rounded-[26px] border border-border bg-surface p-7", i === 0 && "border-[var(--brand)]/40 shadow-[0_20px_60px_-30px_var(--brand-glow)]")}
            >
              <span className={cn("flex size-12 items-center justify-center rounded-[14px] [&_svg]:size-6", i === 0 ? "bg-[var(--brand)] text-white" : "bg-surface-2 text-text")}><Icon /></span>
              <h3 className="mt-6 font-display text-[22px] font-bold">{p.name}</h3>
              <p className="mt-2 text-[15.5px] leading-relaxed text-muted">{p.body}</p>
            </motion.article>
          );
        })}
      </div>
    </section>
  );
}

const FEATURE_ICONS = [Layers3, FileStack, BookOpenCheck, Eye];

function Product({ lang }: { lang: Lang }) {
  const t = COPY[lang].product;
  return (
    <section id="produit" className="scroll-mt-28 bg-surface-2/60 px-6 py-24">
      <SectionHead eyebrow={t.eyebrow} title={t.title} subtitle={t.subtitle} />
      <ol className="mx-auto mt-12 flex max-w-[1120px] flex-wrap items-center justify-center gap-2">
        {t.steps.map((step, i) => (
          <li key={step} className="flex items-center gap-2">
            <span className="flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-2.5 text-[14px] font-medium">
              <span className="flex size-6 items-center justify-center rounded-full bg-[var(--brand)]/12 text-[12px] font-bold text-[var(--brand)]">{i + 1}</span>
              {step}
            </span>
            {i < t.steps.length - 1 ? <ArrowRight className="size-4 text-subtle max-sm:hidden" aria-hidden /> : null}
          </li>
        ))}
      </ol>
      <div className="mx-auto mt-14 grid max-w-[1120px] gap-5 sm:grid-cols-2">
        {t.features.map((f, i) => {
          const Icon = FEATURE_ICONS[i]!;
          return (
            <article key={f.title} className="flex gap-5 rounded-[26px] border border-border bg-surface p-7">
              <span className="flex size-12 shrink-0 items-center justify-center rounded-[14px] bg-[var(--brand)]/10 text-[var(--brand)] [&_svg]:size-6"><Icon /></span>
              <div>
                <h3 className="font-display text-[20px] font-bold">{f.title}</h3>
                <p className="mt-2 text-[15.5px] leading-relaxed text-muted">{f.body}</p>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function UseCases({ lang }: { lang: Lang }) {
  const t = COPY[lang].useCases;
  return (
    <section id="cas-usage" className="scroll-mt-28 px-6 py-24">
      <SectionHead eyebrow={t.eyebrow} title={t.title} />
      <div className="mx-auto mt-14 grid max-w-[1120px] gap-5 md:grid-cols-2">
        {t.items.map((item) => (
          <article key={item.prompt} className="rounded-[26px] border border-border bg-surface p-7">
            <div className="flex items-start gap-3 rounded-[18px] bg-surface-2 px-4 py-3.5">
              <span className="mt-0.5 size-5 shrink-0 rounded-full bg-gradient-to-br from-[#ff9db1] to-[var(--brand)] shadow-[0_0_14px_var(--brand-glow)]" aria-hidden />
              <p className="text-[15.5px] font-medium">{item.prompt}</p>
            </div>
            <p className="mt-4 flex gap-2 text-[15px] leading-relaxed text-muted">
              <ArrowRight className="mt-1 size-4 shrink-0 text-[var(--brand)]" aria-hidden /> {item.result}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

const SECURITY_ICONS = [KeyRound, Lock, Fingerprint, ShieldCheck, ScrollText, ServerCog];

function Security({ lang }: { lang: Lang }) {
  const t = COPY[lang].security;
  return (
    <section id="securite" className="scroll-mt-28 bg-surface-2/60 px-6 py-24">
      <SectionHead eyebrow={t.eyebrow} title={t.title} />
      <div className="mx-auto mt-14 grid max-w-[1120px] gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {t.items.map((item, i) => {
          const Icon = SECURITY_ICONS[i]!;
          return (
            <article key={item.title} className="rounded-[26px] border border-border bg-surface p-7">
              <Icon className="size-6 text-[var(--brand)]" />
              <h3 className="mt-5 text-[18px] font-bold">{item.title}</h3>
              <p className="mt-2 text-[15px] leading-relaxed text-muted">{item.body}</p>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function FinalCta({ lang }: { lang: Lang }) {
  const t = COPY[lang];
  return (
    <section className="px-6 py-24">
      <div className="relative mx-auto max-w-[1120px] overflow-hidden rounded-[34px] bg-[var(--brand)] px-8 py-16 text-center text-white sm:px-16">
        <div aria-hidden className="absolute -right-24 -top-24 size-80 rounded-full bg-white/15 blur-2xl" />
        <div aria-hidden className="absolute -bottom-32 -left-20 size-96 rounded-full bg-[#7a2d8f]/30 blur-3xl" />
        <h2 className="relative font-display text-[32px] font-bold leading-tight sm:text-[44px]">{t.cta.title}</h2>
        <p className="relative mx-auto mt-4 max-w-xl text-[17px] text-white/85">{t.cta.subtitle}</p>
        <div className="relative mt-9 flex flex-wrap justify-center gap-3">
          <a href={demoHref(t.demoSubject)} className="rounded-full bg-white px-8 py-4 text-[17px] font-semibold text-[var(--brand)] transition-transform hover:-translate-y-0.5">{t.bookDemo}</a>
          <Link href="/login" className="rounded-full border border-white/50 px-8 py-4 text-[17px] font-semibold text-white hover:bg-white/10">{t.signIn}</Link>
        </div>
      </div>
    </section>
  );
}

function Footer({ lang }: { lang: Lang }) {
  const t = COPY[lang];
  return (
    <footer className="border-t border-border px-6 py-10">
      <div className="mx-auto flex max-w-[1120px] flex-wrap items-center justify-between gap-6">
        <Brand />
        <p className="text-[14px] text-muted">{t.footer.tagline}</p>
        <p className="text-[13px] text-subtle">© {new Date().getFullYear()} Devoteam. {t.footer.rights}</p>
      </div>
    </footer>
  );
}

export function Landing() {
  const [lang, setLang] = useLang();
  return (
    <div className="landing relative min-h-screen overflow-x-clip bg-background font-landing text-text">
      <div aria-hidden className="pointer-events-none absolute left-1/2 top-[-10%] h-[900px] w-[1300px] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,var(--brand-glow),transparent)] opacity-60" />
      <div className="relative pt-4">
        <Header lang={lang} setLang={setLang} />
        <main>
          <Hero lang={lang} />
          <Vision lang={lang} />
          <Product lang={lang} />
          <UseCases lang={lang} />
          <Security lang={lang} />
          <FinalCta lang={lang} />
        </main>
        <Footer lang={lang} />
      </div>
    </div>
  );
}
