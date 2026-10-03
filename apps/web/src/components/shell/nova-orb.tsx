"use client";

import { cn } from "@nova/ui";
import { motion, useReducedMotion } from "framer-motion";
import { useId } from "react";

import type { NovaPhase } from "@/lib/api/types";

/** NOVA's visible states (the orb is its presence, not a logo). */
export type OrbState = "idle" | "thinking" | "working" | "waiting" | "clarification" | "completed";

export const ORB_LABEL: Record<OrbState, string> = {
  idle: "Ready",
  thinking: "Thinking",
  working: "Working",
  waiting: "Waiting for you",
  clarification: "Needs clarification",
  completed: "Completed",
};

export function orbStateFromPhase(phase: NovaPhase | undefined): OrbState {
  if (phase === "retrieving_context" || phase === "planning") return "thinking";
  if (phase === "executing") return "working";
  if (phase === "waiting_user") return "waiting";
  if (phase === "completed") return "completed";
  return "idle";
}

const MOTION: Record<OrbState, { spin: number; breathe: number; scale: number; halo: string }> = {
  idle: { spin: 48, breathe: 6, scale: 1.02, halo: "rgb(246 71 95 / 0.30)" },
  thinking: { spin: 10, breathe: 2.2, scale: 1.045, halo: "rgb(246 71 95 / 0.42)" },
  working: { spin: 4.5, breathe: 1.4, scale: 1.035, halo: "rgb(246 71 95 / 0.5)" },
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
}: {
  state?: OrbState;
  size?: number;
  reflection?: boolean;
  className?: string;
  title?: string;
}) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const reduce = useReducedMotion();
  const m = MOTION[state];
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
        style={{ inset: -size * (detailed ? 0.28 : 0.22), background: `radial-gradient(circle, ${m.halo}, transparent 68%)` }}
        animate={reduce ? undefined : { scale: [0.92, 1.12, 0.92], opacity: [0.85, 0.45, 0.85] }}
        transition={{ duration: m.breathe, repeat: Infinity, ease: "easeInOut" }}
      />
      {state === "working" && detailed && !reduce ? (
        <motion.span
          className="absolute rounded-full border-2 border-transparent"
          style={{ inset: -size * 0.1, borderTopColor: "rgb(246 71 95 / 0.55)", borderRightColor: "rgb(246 71 95 / 0.18)" }}
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
                <stop offset="0" stopColor="#fffafb" />
                <stop offset="0.55" stopColor="#ffe1e8" />
                <stop offset="0.9" stopColor="#fbbccb" />
                <stop offset="1" stopColor="#f7a5b8" />
              </radialGradient>
              <linearGradient id={id("red")} x1="0.1" y1="0.9" x2="0.9" y2="0.3">
                <stop offset="0" stopColor="#c9102f" />
                <stop offset="0.5" stopColor="#ef3350" />
                <stop offset="1" stopColor="#ff7f93" />
              </linearGradient>
              <linearGradient id={id("pink")} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#ffffff" />
                <stop offset="0.55" stopColor="#ffe6ee" />
                <stop offset="1" stopColor="#f6b3d6" />
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
              <path d="M 118 152 C 146 142, 172 126, 192 106 C 190 150, 162 182, 128 192 Z" fill="#f47fb2" opacity="0.4" />
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
              <stop offset="0.5" stopColor="#ffe1e8" stopOpacity="0.5" />
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
          style={{ top: size * 1.02, width: size * 0.9, height: size * 0.12, background: `radial-gradient(closest-side, ${m.halo}, transparent)` }}
        />
      ) : null}
    </span>
  );
}
