"use client";

import { cn } from "@nova/ui";
import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useId, useRef, useState } from "react";

import type { NovaPhase } from "@/lib/api/types";
import { getLang } from "@/lib/i18n";
import { useUi } from "@/stores/ui";

/** NOVA's visible states (the orb is its presence, not a logo). `listening`/`speaking` are reserved for voice. */
export type OrbState = "idle" | "thinking" | "working" | "waiting" | "clarification" | "completed" | "listening" | "speaking";

const ORB_LABEL_TEXT: Record<OrbState, { en: string; fr: string }> = {
  idle: { en: "Ready", fr: "Prêt" },
  thinking: { en: "Thinking", fr: "Réfléchit" },
  working: { en: "Working", fr: "Travaille" },
  waiting: { en: "Waiting for you", fr: "Vous attend" },
  clarification: { en: "Needs clarification", fr: "Besoin d’une précision" },
  completed: { en: "Completed", fr: "Terminé" },
  listening: { en: "Listening", fr: "Écoute" },
  speaking: { en: "Speaking", fr: "Parle" },
};

/** Localized labels (read in the current interface language). */
export const ORB_LABEL = Object.defineProperties(
  {} as Record<OrbState, string>,
  Object.fromEntries(Object.keys(ORB_LABEL_TEXT).map((k) => [k, { enumerable: true, get: () => ORB_LABEL_TEXT[k as OrbState][getLang()] }])),
);

export function orbStateFromPhase(phase: NovaPhase | undefined): OrbState {
  if (phase === "retrieving_context" || phase === "planning") return "thinking";
  if (phase === "executing") return "working";
  if (phase === "waiting_user") return "waiting";
  if (phase === "completed") return "completed";
  return "idle";
}

/** The 7 orb colors a user can choose in Settings (coral is devoteam's). */
export const ORB_PALETTES = {
  coral: { label: "Coral", body: ["#fffafb", "#ffe1e8", "#fbbccb", "#f7a5b8"], mass: ["#c9102f", "#ef3350", "#ff7f93"], light: ["#ffffff", "#ffe6ee", "#f6b3d6"], accent: "#f47fb2", glow: "246 71 95" },
  rose: { label: "Rose", body: ["#fffafd", "#ffe3f1", "#fbbfdc", "#f5a3cc"], mass: ["#be185d", "#ec4899", "#f9a8d4"], light: ["#ffffff", "#fde7f3", "#f5c2e7"], accent: "#c084fc", glow: "236 72 153" },
  violet: { label: "Violet", body: ["#fcfaff", "#ede4ff", "#d4c2fb", "#c3acf7"], mass: ["#5b21b6", "#8b5cf6", "#c4b5fd"], light: ["#ffffff", "#efe8ff", "#e0ccff"], accent: "#f0abfc", glow: "139 92 246" },
  ocean: { label: "Ocean", body: ["#f8fcff", "#e0efff", "#b9d7fb", "#a3c8f7"], mass: ["#1d4ed8", "#3b82f6", "#93c5fd"], light: ["#ffffff", "#e6f2ff", "#c7defd"], accent: "#67e8f9", glow: "59 130 246" },
  emerald: { label: "Emerald", body: ["#f8fffb", "#dcf7ea", "#b3ead0", "#9ae0c0"], mass: ["#047857", "#10b981", "#6ee7b7"], light: ["#ffffff", "#e3faef", "#c3f0dc"], accent: "#a3e635", glow: "16 185 129" },
  amber: { label: "Amber", body: ["#fffdf7", "#fff1d6", "#fcd9a0", "#f9c97e"], mass: ["#b45309", "#f59e0b", "#fcd34d"], light: ["#ffffff", "#fff4dc", "#fde2a8"], accent: "#fb923c", glow: "245 158 11" },
  graphite: { label: "Graphite", body: ["#fbfbfc", "#e9eaee", "#c9ccd4", "#b5b9c3"], mass: ["#1f2937", "#4b5563", "#9ca3af"], light: ["#ffffff", "#eef0f3", "#d6d9df"], accent: "#a5b4fc", glow: "75 85 99" },
} as const;
export type OrbPalette = keyof typeof ORB_PALETTES;

// --- The 12 looks of the orb (art direction "NOVA / Les états de l’orb") -------------------------

export type OrbLook =
  | "veille"
  | "activation"
  | "rubans"
  | "tourbillon"
  | "concentration"
  | "impulsion"
  | "ondes"
  | "convergence"
  | "lumiere"
  | "coeur"
  | "eclat"
  | "calme";

/** Ribbon paths (200×200 sphere): wide translucent band + red core + light edge. */
const RIBBONS = [
  "M -20 112 C 40 70, 110 160, 220 96", // 0 horizontal wave
  "M -20 150 C 50 118, 112 122, 220 40", // 1 rising diagonal
  "M -20 58 C 60 92, 140 150, 220 172", // 2 falling diagonal
  "M 26 -20 C 62 80, 136 118, 176 220", // 3 steep, left
  "M 42 220 C 72 120, 120 82, 162 -20", // 4 steep, right
  "M -20 132 C 70 156, 130 52, 220 72", // 5 counter wave
] as const;

interface Look {
  ribbons: number[]; // visible ribbon indexes
  band: number; // opacity of the wide light band
  red: number; // opacity of the red core
  rotate: number; // base rotation of the ribbon group
  spin: number; // seconds per turn (0 = still)
  tint: number; // pink tint of the glass
  grey: number; // grey marble glass
  bokeh: number;
  white: number; // white light filling the sphere
  gold: number; // golden glass
  core: number; // bright core
  burst: number; // star burst
}

const LOOKS: Record<OrbLook, Look> = {
  veille: { ribbons: [0], band: 0.35, red: 0.3, rotate: -18, spin: 0, tint: 0.05, grey: 0.75, bokeh: 0.7, white: 0, gold: 0, core: 0, burst: 0 },
  activation: { ribbons: [1, 2], band: 0.85, red: 0.55, rotate: 0, spin: 0, tint: 0.4, grey: 0.25, bokeh: 0.45, white: 0, gold: 0, core: 0, burst: 0 },
  rubans: { ribbons: [1, 2, 3], band: 0.8, red: 0.85, rotate: 8, spin: 18, tint: 0.25, grey: 0.4, bokeh: 0.35, white: 0, gold: 0, core: 0, burst: 0 },
  tourbillon: { ribbons: [1, 3, 4, 5], band: 0.7, red: 0.95, rotate: 20, spin: 5, tint: 0.1, grey: 0.55, bokeh: 0.2, white: 0, gold: 0, core: 0, burst: 0 },
  concentration: { ribbons: [3, 4], band: 0.8, red: 1, rotate: -8, spin: 0, tint: 0.05, grey: 0.6, bokeh: 0.35, white: 0, gold: 0, core: 0, burst: 0 },
  impulsion: { ribbons: [1, 2], band: 0.25, red: 0.25, rotate: 0, spin: 0, tint: 0.55, grey: 0, bokeh: 0, white: 0.15, gold: 0, core: 0.95, burst: 1 },
  ondes: { ribbons: [0, 1, 2, 5], band: 0.85, red: 0.7, rotate: 0, spin: 24, tint: 0.45, grey: 0.15, bokeh: 0.2, white: 0, gold: 0, core: 0, burst: 0 },
  convergence: { ribbons: [0, 2, 5], band: 0.85, red: 0.9, rotate: -6, spin: 30, tint: 0.2, grey: 0.4, bokeh: 0.2, white: 0, gold: 0, core: 0, burst: 0 },
  lumiere: { ribbons: [0, 5], band: 0.35, red: 0, rotate: 0, spin: 0, tint: 0, grey: 0, bokeh: 0, white: 0.85, gold: 0, core: 0.3, burst: 0 },
  coeur: { ribbons: [], band: 0, red: 0, rotate: 0, spin: 0, tint: 0, grey: 0, bokeh: 0, white: 0.1, gold: 0.75, core: 1, burst: 0 },
  eclat: { ribbons: [1], band: 0.3, red: 0.3, rotate: 0, spin: 0, tint: 0.15, grey: 0, bokeh: 0, white: 0, gold: 0.45, core: 0.85, burst: 0.85 },
  calme: { ribbons: [0, 5], band: 0.8, red: 0.85, rotate: 0, spin: 0, tint: 0.05, grey: 0.7, bokeh: 0.55, white: 0, gold: 0, core: 0, burst: 0 },
};

/** How each NOVA state is told with the looks: a loop (cycle) or a one-shot sequence ending on a resting look. */
const CHOREOGRAPHY: Record<OrbState, { looks: OrbLook[]; step: number; loop: boolean }> = {
  idle: { looks: ["veille"], step: 0, loop: false },
  thinking: { looks: ["activation", "rubans"], step: 1400, loop: true },
  working: { looks: ["tourbillon", "concentration", "convergence"], step: 1800, loop: true },
  waiting: { looks: ["activation", "veille"], step: 2200, loop: true },
  clarification: { looks: ["ondes", "activation"], step: 1600, loop: true },
  completed: { looks: ["impulsion", "lumiere", "coeur", "eclat", "calme"], step: 520, loop: false },
  listening: { looks: ["activation"], step: 0, loop: false },
  speaking: { looks: ["ondes", "convergence"], step: 900, loop: true },
};

function useLook(state: OrbState, animate: boolean): OrbLook {
  const plan = CHOREOGRAPHY[state];
  const first = useRef(true);
  // On first render a completed orb rests on its final look (the celebration plays only on a live transition).
  const [index, setIndex] = useState(() => (state === "completed" ? plan.looks.length - 1 : 0));
  useEffect(() => {
    const isFirst = first.current;
    first.current = false;
    if (!animate || plan.looks.length < 2) {
      setIndex(state === "completed" ? plan.looks.length - 1 : 0);
      return;
    }
    if (state === "completed" && isFirst) return;
    setIndex(0);
    let i = 0;
    const timer = setInterval(() => {
      i += 1;
      if (!plan.loop && i >= plan.looks.length - 1) {
        setIndex(plan.looks.length - 1);
        clearInterval(timer);
        return;
      }
      setIndex(i % plan.looks.length);
    }, plan.step);
    return () => clearInterval(timer);
  }, [state, animate, plan]);
  return plan.looks[Math.min(index, plan.looks.length - 1)] ?? "veille";
}

const BOKEH = [
  [62, 70, 3.2], [84, 58, 2.4], [120, 64, 2.8], [140, 84, 2], [70, 118, 3], [102, 132, 2.6],
  [136, 128, 3.4], [58, 96, 1.8], [152, 110, 2.2], [94, 92, 1.6],
] as const;

const TRANSITION = { duration: 0.65, ease: [0.4, 0, 0.2, 1] as const };

/**
 * NOVA's orb: a glass marble with translucent ribbons, warm bokeh and an inner light. Its 12 looks
 * (veille → retour au calme) are choreographed per state; colors follow the user's palette.
 */
export function NovaOrb({
  state = "idle",
  size = 32,
  reflection = false,
  className,
  title,
  color,
}: {
  state?: OrbState;
  size?: number;
  reflection?: boolean;
  className?: string;
  title?: string;
  /** Overrides the user's chosen color (Settings preview). */
  color?: OrbPalette;
}) {
  const chosen = useUi((s) => s.orbColor);
  const palette = ORB_PALETTES[color ?? chosen] ?? ORB_PALETTES.coral;
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const reduce = useReducedMotion();
  const detailed = size >= 44;
  const look = useLook(state, !reduce);
  const L = LOOKS[look];
  const id = (name: string) => `${name}-${uid}`;
  const haloColor =
    state === "waiting" ? "245 158 11" : state === "clarification" ? "168 85 247" : look === "coeur" || look === "eclat" ? "246 196 120" : palette.glow;
  const haloOpacity = state === "working" || state === "speaking" ? 0.42 : state === "idle" ? 0.18 : 0.3;
  const visible = (i: number) => L.ribbons.includes(i);
  const ribbons = detailed ? RIBBONS : RIBBONS.filter((_, i) => i < 4);

  return (
    <span
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      className={cn("relative inline-flex shrink-0 items-center justify-center", className)}
      style={{ width: size, height: size }}
      data-orb-state={state}
      data-orb-look={look}
    >
      <motion.span
        className="absolute rounded-full"
        style={{ inset: -size * (detailed ? 0.26 : 0.2), background: `radial-gradient(circle, rgb(${haloColor} / ${haloOpacity}), transparent 68%)` }}
        animate={reduce ? undefined : { scale: [0.94, 1.1, 0.94], opacity: [0.9, 0.5, 0.9] }}
        transition={{ duration: state === "working" ? 1.4 : state === "idle" ? 6 : 2.6, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.span
        className="relative block size-full"
        animate={reduce ? undefined : { scale: state === "idle" ? [1, 1.015, 1] : [1, 1.03, 1] }}
        transition={{ duration: state === "idle" ? 6 : 2.2, repeat: Infinity, ease: "easeInOut" }}
      >
        <svg viewBox="0 0 200 200" className="size-full overflow-visible">
          <defs>
            <clipPath id={id("clip")}>
              <circle cx="100" cy="100" r="93" />
            </clipPath>
            <radialGradient id={id("glass")} cx="0.5" cy="0.42" r="0.62">
              <stop offset="0" stopColor="#f7f3f3" />
              <stop offset="0.7" stopColor="#ddd5d8" />
              <stop offset="1" stopColor="#a79ea3" />
            </radialGradient>
            <radialGradient id={id("pinkglass")} cx="0.5" cy="0.45" r="0.6">
              <stop offset="0" stopColor={palette.body[0]} />
              <stop offset="0.75" stopColor={palette.body[2]} />
              <stop offset="1" stopColor={palette.body[3]} />
            </radialGradient>
            <radialGradient id={id("gold")} cx="0.5" cy="0.5" r="0.55">
              <stop offset="0" stopColor="#fff6e6" />
              <stop offset="0.7" stopColor="#f3d7b0" />
              <stop offset="1" stopColor="#e3b98a" />
            </radialGradient>
            <radialGradient id={id("core")} cx="0.5" cy="0.5" r="0.5">
              <stop offset="0" stopColor="#ffffff" />
              <stop offset="0.45" stopColor="#fffaf0" stopOpacity="0.95" />
              <stop offset="1" stopColor="#fff2dc" stopOpacity="0" />
            </radialGradient>
            <linearGradient id={id("band")} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor={palette.light[0]} />
              <stop offset="0.5" stopColor={palette.light[1]} />
              <stop offset="1" stopColor={palette.light[2]} />
            </linearGradient>
            <linearGradient id={id("red")} x1="0" y1="1" x2="1" y2="0">
              <stop offset="0" stopColor={palette.mass[0]} />
              <stop offset="0.55" stopColor={palette.mass[1]} />
              <stop offset="1" stopColor={palette.mass[2]} />
            </linearGradient>
            {detailed ? (
              <>
                <filter id={id("soft")} x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="1.6" />
                </filter>
                <filter id={id("blur")} x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="6" />
                </filter>
              </>
            ) : null}
          </defs>

          <g clipPath={`url(#${id("clip")})`}>
            {/* glass: grey marble ↔ tinted ↔ white light ↔ gold */}
            <circle cx="100" cy="100" r="93" fill={`url(#${id("pinkglass")})`} />
            <motion.circle cx="100" cy="100" r="93" fill={`url(#${id("glass")})`} initial={false} animate={{ opacity: L.grey }} transition={TRANSITION} />
            <motion.circle cx="100" cy="100" r="93" fill={palette.body[2]} initial={false} animate={{ opacity: L.tint * 0.6 }} transition={TRANSITION} />
            <motion.circle cx="100" cy="100" r="93" fill={`url(#${id("gold")})`} initial={false} animate={{ opacity: L.gold }} transition={TRANSITION} />

            {/* bokeh */}
            <motion.g initial={false} animate={{ opacity: L.bokeh }} transition={TRANSITION} filter={detailed ? `url(#${id("soft")})` : undefined}>
              {(detailed ? BOKEH : BOKEH.slice(0, 5)).map(([cx, cy, r], i) => (
                <ellipse key={i} cx={cx} cy={cy} rx={r * 1.3} ry={r} fill="#fff1d2" opacity={0.85} />
              ))}
            </motion.g>

            {/* ribbons */}
            <motion.g
              initial={false}
              animate={{ rotate: L.rotate }}
              transition={TRANSITION}
              style={{ transformOrigin: "100px 100px", transformBox: "view-box" }}
            >
              <motion.g
                animate={!reduce && L.spin ? { rotate: 360 } : { rotate: 0 }}
                transition={L.spin ? { duration: L.spin, repeat: Infinity, ease: "linear" } : { duration: 0.6 }}
                style={{ transformOrigin: "100px 100px", transformBox: "view-box" }}
              >
                {ribbons.map((d, i) => (
                  <motion.g key={i} initial={false} animate={{ opacity: visible(i) ? 1 : 0 }} transition={TRANSITION}>
                    <motion.path
                      d={d}
                      fill="none"
                      stroke={`url(#${id("band")})`}
                      strokeWidth={detailed ? 48 : 44}
                      strokeLinecap="round"
                      initial={false}
                      animate={{ opacity: L.band }}
                      transition={TRANSITION}
                    />
                    <motion.path
                      d={d}
                      fill="none"
                      stroke={`url(#${id("red")})`}
                      strokeWidth={detailed ? 20 : 22}
                      strokeLinecap="round"
                      transform="translate(0 9)"
                      initial={false}
                      animate={{ opacity: L.red }}
                      transition={TRANSITION}
                      filter={detailed ? `url(#${id("soft")})` : undefined}
                    />
                    {detailed ? <path d={d} fill="none" stroke="#fff" strokeWidth="2" opacity={0.7 * L.band} transform="translate(0 -20)" /> : null}
                  </motion.g>
                ))}
              </motion.g>
            </motion.g>

            {/* white light, core and burst */}
            <motion.circle cx="100" cy="100" r="93" fill="#fbfefe" initial={false} animate={{ opacity: L.white }} transition={TRANSITION} />
            <motion.circle
              cx="100"
              cy="100"
              r="62"
              fill={`url(#${id("core")})`}
              initial={false}
              animate={{ opacity: L.core, scale: L.core ? 1 : 0.6 }}
              transition={TRANSITION}
              style={{ transformOrigin: "100px 100px", transformBox: "view-box" }}
            />
            <motion.g
              initial={false}
              animate={{ opacity: L.burst, rotate: L.burst ? 18 : 0, scale: L.burst ? 1 : 0.5 }}
              transition={TRANSITION}
              style={{ transformOrigin: "100px 100px", transformBox: "view-box" }}
              filter={detailed ? `url(#${id("blur")})` : undefined}
            >
              {Array.from({ length: 14 }, (_, i) => (
                <path key={i} d="M 100 100 L 96 34 L 100 22 L 104 34 Z" fill="#fff" transform={`rotate(${(360 / 14) * i} 100 100)`} />
              ))}
            </motion.g>
          </g>

          {/* glass rim + specular highlight (fixed) */}
          <circle cx="100" cy="100" r="92" fill="none" stroke="#6f666b" strokeOpacity={detailed ? 0.35 : 0.25} strokeWidth={detailed ? 3 : 6} />
          <circle cx="100" cy="100" r="88" fill="none" stroke="#fff" strokeOpacity="0.5" strokeWidth={detailed ? 2.5 : 0} />
          <path d="M 44 54 A 70 70 0 0 1 118 24" fill="none" stroke="#fff" strokeOpacity={detailed ? 0.8 : 0.7} strokeWidth={detailed ? 5 : 9} strokeLinecap="round" />
          {detailed ? <path d="M 150 158 A 70 70 0 0 1 112 172" fill="none" stroke="#fff" strokeOpacity="0.35" strokeWidth="3" strokeLinecap="round" /> : null}
        </svg>
      </motion.span>
      {reflection ? (
        <span
          aria-hidden
          className="absolute left-1/2 -translate-x-1/2 rounded-full"
          style={{ top: size * 1.02, width: size * 0.9, height: size * 0.12, background: `radial-gradient(closest-side, rgb(${haloColor} / 0.35), transparent)` }}
        />
      ) : null}
    </span>
  );
}
