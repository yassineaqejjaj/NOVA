"use client";

import { cn } from "@nova/ui";
import { motion, useReducedMotion } from "framer-motion";
import { useId } from "react";

import { getLang } from "@/lib/i18n";
import { useUi } from "@/stores/ui";

import type { NovaPhase } from "@/lib/api/types";

/** NOVA's visible states (the orb is its presence, not a logo). */
export type OrbState = "idle" | "thinking" | "working" | "waiting" | "clarification" | "completed";

const ORB_LABEL_TEXT: Record<OrbState, { en: string; fr: string }> = {
  idle: { en: "Ready", fr: "Prêt" },
  thinking: { en: "Thinking", fr: "Réfléchit" },
  working: { en: "Working", fr: "Travaille" },
  waiting: { en: "Waiting for you", fr: "Vous attend" },
  clarification: { en: "Needs clarification", fr: "Besoin d’une précision" },
  completed: { en: "Completed", fr: "Terminé" },
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

const MOTION: Record<OrbState, { spin: number; breathe: number; scale: number; halo: string | null }> = {
  idle: { spin: 48, breathe: 6, scale: 1.02, halo: null },
  thinking: { spin: 10, breathe: 2.2, scale: 1.045, halo: null },
  working: { spin: 4.5, breathe: 1.4, scale: 1.035, halo: null },
  waiting: { spin: 30, breathe: 2.6, scale: 1.03, halo: "rgb(245 158 11 / 0.38)" },
  clarification: { spin: 22, breathe: 2, scale: 1.03, halo: "rgb(168 85 247 / 0.32)" },
  completed: { spin: 36, breathe: 4, scale: 1.02, halo: "rgb(16 185 129 / 0.30)" },
};

/**
 * Glass orb with a red/pink S-wave inside (rotating), a fixed rim and specular highlight, and a halo whose
 * color and rhythm express NOVA's state. Pure SVG: crisp at any size, no image download.
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
  const m = MOTION[state];
  const intensity = state === "working" ? 0.5 : state === "thinking" ? 0.42 : 0.3;
  const halo = m.halo ?? `rgb(${palette.glow} / ${intensity})`;
  const detailed = size >= 44;
  const id = (name: string) => `${name}-${uid}`;
  return (
    <span
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      className={cn("relative inline-flex shrink-0 items-center justify-center", className)}
      style={{ width: size, height: size }}
    >
      {/* halo */}
      <motion.span
        className="absolute rounded-full"
        style={{ inset: -size * (detailed ? 0.28 : 0.22), background: `radial-gradient(circle, ${halo}, transparent 68%)` }}
        animate={reduce ? undefined : { scale: [0.92, 1.12, 0.92], opacity: [0.85, 0.45, 0.85] }}
        transition={{ duration: m.breathe, repeat: Infinity, ease: "easeInOut" }}
      />
      {state === "working" && detailed && !reduce ? (
        <motion.span
          className="absolute rounded-full border-2 border-transparent"
          style={{ inset: -size * 0.1, borderTopColor: `rgb(${palette.glow} / 0.55)`, borderRightColor: `rgb(${palette.glow} / 0.18)` }}
          animate={{ rotate: 360 }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "linear" }}
        />
      ) : null}
      <motion.span
        className="relative block size-full"
        animate={reduce ? undefined : state === "clarification" ? { rotate: [-4, 4, -4], scale: [1, m.scale, 1] } : { scale: [1, m.scale, 1] }}
        transition={{ duration: m.breathe, repeat: Infinity, ease: "easeInOut" }}
      >
        {/* glass body + rotating wave */}
        <motion.span
          className="absolute inset-0"
          animate={reduce ? undefined : { rotate: 360 }}
          transition={{ duration: m.spin, repeat: Infinity, ease: "linear" }}
        >
          <svg viewBox="0 0 200 200" className="size-full overflow-visible">
            <defs>
              <radialGradient id={id("body")} cx="0.5" cy="0.45" r="0.62">
                <stop offset="0" stopColor={palette.body[0]} />
                <stop offset="0.55" stopColor={palette.body[1]} />
                <stop offset="0.9" stopColor={palette.body[2]} />
                <stop offset="1" stopColor={palette.body[3]} />
              </radialGradient>
              <linearGradient id={id("red")} x1="0.1" y1="0.9" x2="0.9" y2="0.3">
                <stop offset="0" stopColor={palette.mass[0]} />
                <stop offset="0.5" stopColor={palette.mass[1]} />
                <stop offset="1" stopColor={palette.mass[2]} />
              </linearGradient>
              <linearGradient id={id("pink")} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor={palette.light[0]} />
                <stop offset="0.55" stopColor={palette.light[1]} />
                <stop offset="1" stopColor={palette.light[2]} />
              </linearGradient>
              <clipPath id={id("clip")}>
                <circle cx="100" cy="100" r="92" />
              </clipPath>
              {detailed ? (
                <>
                  <filter id={id("soft")} x="-20%" y="-20%" width="140%" height="140%">
                    <feGaussianBlur stdDeviation="2.4" />
                  </filter>
                  <filter id={id("glow")} x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="5" />
                  </filter>
                </>
              ) : null}
            </defs>
            <g clipPath={`url(#${id("clip")})`}>
              <circle cx="100" cy="100" r="92" fill={`url(#${id("body")})`} />
              {/* pale upper-right lobe */}
              <path
                d="M 34 46 C 66 12, 146 8, 182 56 C 198 92, 178 124, 146 118 C 116 112, 104 84, 76 78 C 56 74, 40 64, 34 46 Z"
                fill={`url(#${id("pink")})`}
                opacity="0.9"
                filter={detailed ? `url(#${id("soft")})` : undefined}
              />
              {/* red mass, lower left */}
              <path
                d="M 14 98 C 30 70, 76 76, 98 102 C 120 128, 150 150, 178 134 C 168 176, 124 198, 82 190 C 40 182, 6 142, 14 98 Z"
                fill={`url(#${id("red")})`}
                opacity="0.92"
                filter={detailed ? `url(#${id("soft")})` : undefined}
              />
              {/* soft magenta lobe, lower right */}
              <path d="M 118 152 C 146 142, 172 126, 192 106 C 190 150, 162 182, 128 192 Z" fill={palette.accent} opacity="0.4" />
              {/* luminous S */}
              {detailed ? (
                <path
                  d="M 42 72 C 78 58, 94 96, 110 110 S 152 142, 178 128"
                  fill="none"
                  stroke="#fff"
                  strokeWidth="12"
                  strokeLinecap="round"
                  opacity="0.45"
                  filter={`url(#${id("glow")})`}
                />
              ) : null}
              <path
                d="M 42 72 C 78 58, 94 96, 110 110 S 152 142, 178 128"
                fill="none"
                stroke="#fff"
                strokeWidth={detailed ? 3.5 : 7}
                strokeLinecap="round"
                opacity="0.95"
              />
            </g>
          </svg>
        </motion.span>
        {/* fixed rim + specular */}
        <svg viewBox="0 0 200 200" className="absolute inset-0 size-full overflow-visible">
          <defs>
            <linearGradient id={id("rim")} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#ffffff" stopOpacity="0.95" />
              <stop offset="0.5" stopColor={palette.body[1]} stopOpacity="0.5" />
              <stop offset="1" stopColor="#ffffff" stopOpacity="0.85" />
            </linearGradient>
          </defs>
          <circle cx="100" cy="100" r="91" fill="none" stroke={`url(#${id("rim")})`} strokeWidth={detailed ? 2.5 : 6} />
          <circle cx="100" cy="100" r="86" fill="none" stroke="#fff" strokeOpacity="0.35" strokeWidth={detailed ? 6 : 0} />
          <ellipse cx="66" cy="44" rx="22" ry="7" fill="#fff" opacity={detailed ? 0.55 : 0.7} transform="rotate(-30 66 44)" />
        </svg>
      </motion.span>
      {reflection ? (
        <span
          aria-hidden
          className="absolute left-1/2 -translate-x-1/2 rounded-full"
          style={{ top: size * 1.02, width: size * 0.9, height: size * 0.12, background: `radial-gradient(closest-side, ${halo}, transparent)` }}
        />
      ) : null}
    </span>
  );
}
