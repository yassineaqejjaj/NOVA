"use client";

import { cn } from "@nova/ui";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

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

/**
 * The 7 orb colors (Settings). The artwork is devoteam coral; other colors are a hue shift of the same
 * footage so every look and motion is preserved. `glow` colors the halo.
 */
export const ORB_PALETTES = {
  coral: { label: "Coral", filter: "none", glow: "246 71 95" },
  rose: { label: "Rose", filter: "hue-rotate(-22deg) saturate(1.05)", glow: "236 72 153" },
  violet: { label: "Violet", filter: "hue-rotate(-82deg) saturate(0.95)", glow: "139 92 246" },
  ocean: { label: "Ocean", filter: "hue-rotate(-140deg) saturate(0.95)", glow: "59 130 246" },
  emerald: { label: "Emerald", filter: "hue-rotate(160deg) saturate(0.85)", glow: "16 185 129" },
  amber: { label: "Amber", filter: "hue-rotate(48deg) saturate(1.1)", glow: "245 158 11" },
  graphite: { label: "Graphite", filter: "grayscale(1) contrast(1.08)", glow: "75 85 99" },
} as const;
export type OrbPalette = keyof typeof ORB_PALETTES;

// --- Footage: public/orb/orb.mp4 — one segment per state; loops play forward and are seamless (crossfade
// encoded at the loop point), calm states are slowed down with motion interpolation -----------------------

const VIDEO = "/orb/orb.mp4";
// Frame-exact boundaries of public/orb/orb.mp4 (24 fps; regenerate with infrastructure/orb/build_orb_assets.py).
const SEGMENTS = {
  idle: [0, 1.2917],
  thinking: [1.2917, 3.4583],
  working: [3.4583, 5.0],
  waiting: [5.0, 6.375],
  clarification: [6.375, 7.7917],
  completed: [7.7917, 11.375], // one shot: impulsion → lumière blanche → cœur doré → éclat final → retour au calme
  calm: [11.375, 12.875],
} as const;
type Segment = keyof typeof SEGMENTS;

const STATE_SEGMENT: Record<OrbState, Segment> = {
  idle: "idle",
  thinking: "thinking",
  working: "working",
  waiting: "waiting",
  clarification: "clarification",
  completed: "completed",
  listening: "waiting",
  speaking: "clarification",
};

// --- Stills: the 12 looks, for small orbs and reduced motion ----------------------------------------

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

/** How small orbs tell each state with stills: a cycle, or a one-shot sequence resting on its last look. */
const CHOREOGRAPHY: Record<OrbState, { looks: OrbLook[]; step: number; loop: boolean }> = {
  idle: { looks: ["veille"], step: 0, loop: false },
  thinking: { looks: ["activation", "rubans"], step: 2600, loop: true },
  working: { looks: ["tourbillon", "concentration", "convergence"], step: 2200, loop: true },
  waiting: { looks: ["activation", "veille"], step: 3200, loop: true },
  clarification: { looks: ["ondes", "activation"], step: 2600, loop: true },
  completed: { looks: ["impulsion", "lumiere", "coeur", "eclat", "calme"], step: 800, loop: false },
  listening: { looks: ["activation"], step: 0, loop: false },
  speaking: { looks: ["ondes", "convergence"], step: 1600, loop: true },
};

const still = (look: OrbLook) => `/orb/${look}.webp`;

function useLook(state: OrbState, animate: boolean): OrbLook {
  const plan = CHOREOGRAPHY[state];
  const first = useRef(true);
  // A completed orb rendered for the first time rests on its final look (the celebration plays on live transitions).
  const [index, setIndex] = useState(() => (state === "completed" ? plan.looks.length - 1 : 0));
  useEffect(() => {
    const isFirst = first.current;
    first.current = false;
    if (!animate || plan.looks.length < 2 || (state === "completed" && isFirst)) {
      setIndex(state === "completed" ? plan.looks.length - 1 : 0);
      return;
    }
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

const CROSSFADE_MS = 650;

/**
 * Plays the state's segment of the footage (completed: once, then the calm loop). Loops wrap at their encoded
 * seam; changing state crossfades: the current frame is frozen on a canvas that fades out while the new segment
 * starts underneath, so the orb never jumps.
 */
function useSegmentPlayer(
  video: React.RefObject<HTMLVideoElement | null>,
  canvas: React.RefObject<HTMLCanvasElement | null>,
  state: OrbState,
  enabled: boolean,
) {
  const first = useRef(true);
  useEffect(() => {
    const el = video.current;
    if (!el || !enabled) return;
    const isFirst = first.current;
    first.current = false;
    let segment: Segment = state === "completed" && isFirst ? "calm" : STATE_SEGMENT[state];
    let frame = 0;
    let fade = 0;

    const freeze = () => {
      const c = canvas.current;
      if (!c || isFirst || el.readyState < 2) return;
      c.width = el.videoWidth;
      c.height = el.videoHeight;
      c.getContext("2d")?.drawImage(el, 0, 0);
      c.style.transition = "none";
      c.style.opacity = "1";
      window.clearTimeout(fade);
      fade = window.setTimeout(() => {
        c.style.transition = `opacity ${CROSSFADE_MS}ms cubic-bezier(0.4, 0, 0.2, 1)`;
        c.style.opacity = "0";
      }, 30);
    };
    const start = () => {
      freeze();
      el.currentTime = SEGMENTS[segment][0];
      void el.play().catch(() => undefined); // autoplay can be refused (power saving): the poster stays visible
    };
    const tick = () => {
      const [from, to] = SEGMENTS[segment];
      if (el.currentTime >= to - 1 / 48 || el.currentTime < from - 0.25) {
        if (segment === "completed") {
          segment = "calm";
          freeze();
        }
        el.currentTime = SEGMENTS[segment][0]; // seamless: the loop's last frame flows into its first
      }
      frame = requestAnimationFrame(tick);
    };
    const onEnded = () => {
      if (segment === "completed") segment = "calm";
      start();
    };
    if (el.readyState >= 1) start();
    else el.addEventListener("loadedmetadata", start, { once: true });
    el.addEventListener("ended", onEnded);
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(fade);
      el.removeEventListener("loadedmetadata", start);
      el.removeEventListener("ended", onEnded);
    };
  }, [video, canvas, state, enabled]);
}

/** A stable per-instance phase so several orbs on screen never breathe in sync. */
function usePhase(): number {
  const [phase] = useState(() => Math.random());
  return phase;
}

const HALO: Record<OrbState, { opacity: number; breathe: number }> = {
  idle: { opacity: 0.16, breathe: 7 },
  thinking: { opacity: 0.28, breathe: 3.6 },
  working: { opacity: 0.36, breathe: 2.8 },
  waiting: { opacity: 0.26, breathe: 4.4 },
  clarification: { opacity: 0.28, breathe: 3.6 },
  completed: { opacity: 0.24, breathe: 5.5 },
  listening: { opacity: 0.3, breathe: 3.2 },
  speaking: { opacity: 0.34, breathe: 2.6 },
};

const SPHERE_MASK = "radial-gradient(circle closest-side, #000 92.5%, transparent 94.5%)";

/**
 * NOVA's orb: a glass marble with silk ribbons (art direction video). Large orbs play the footage segment of
 * the current state; small ones crossfade the 12 still looks. Colors follow the user's palette.
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
  const reduce = useReducedMotion();
  const useVideo = size >= 44 && !reduce;
  const look = useLook(state, !reduce && !useVideo);
  const video = useRef<HTMLVideoElement>(null);
  const freezeFrame = useRef<HTMLCanvasElement>(null);
  useSegmentPlayer(video, freezeFrame, state, useVideo);
  const phase = usePhase();

  const haloColor = state === "waiting" ? "245 158 11" : state === "clarification" ? "168 85 247" : palette.glow;
  const halo = HALO[state];
  const restingLook: OrbLook = state === "completed" ? "calme" : CHOREOGRAPHY[state].looks[0] ?? "veille";

  return (
    <span
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      className={cn("relative inline-flex shrink-0 items-center justify-center", className)}
      style={{ width: size, height: size }}
      data-orb-state={state}
    >
      {/* Halo: its color crossfades between states; it breathes slowly, out of phase with other orbs. */}
      <AnimatePresence initial={false}>
        <motion.span
          key={haloColor}
          className="absolute rounded-full"
          style={{ inset: -size * (size >= 44 ? 0.24 : 0.18), background: `radial-gradient(circle, rgb(${haloColor} / 1), transparent 68%)` }}
          initial={{ opacity: 0 }}
          animate={reduce ? { opacity: halo.opacity } : { opacity: [halo.opacity, halo.opacity * 0.62, halo.opacity], scale: [0.97, 1.05, 0.97] }}
          exit={{ opacity: 0, transition: { duration: 0.9 } }}
          transition={{ duration: halo.breathe, repeat: Infinity, ease: "easeInOut", delay: -phase * halo.breathe, opacity: { duration: halo.breathe, repeat: Infinity, ease: "easeInOut" } }}
        />
      </AnimatePresence>
      <motion.span
        className="relative block size-full"
        style={{ filter: palette.filter === "none" ? undefined : palette.filter }}
        // Small orbs (stills) drift a little so they never look frozen; the footage moves on its own.
        animate={reduce || useVideo ? undefined : { rotate: [-2.5, 2.5, -2.5], scale: [1, 1.02, 1] }}
        transition={{ duration: 9, repeat: Infinity, ease: "easeInOut", delay: -phase * 9 }}
      >
        {useVideo ? (
          <video
            ref={video}
            src={VIDEO}
            poster={still(restingLook)}
            muted
            playsInline
            autoPlay
            preload="auto"
            disablePictureInPicture
            aria-hidden
            className="size-full object-cover"
            style={{ maskImage: SPHERE_MASK, WebkitMaskImage: SPHERE_MASK }}
          />
        ) : null}
        {useVideo ? (
          <canvas
            ref={freezeFrame}
            aria-hidden
            className="pointer-events-none absolute inset-0 size-full opacity-0"
            style={{ maskImage: SPHERE_MASK, WebkitMaskImage: SPHERE_MASK }}
          />
        ) : (
          <AnimatePresence initial={false}>
            { }
            <motion.img
              key={look}
              src={still(reduce ? restingLook : look)}
              alt=""
              draggable={false}
              className="absolute inset-0 size-full select-none"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 1.1, ease: [0.4, 0, 0.2, 1] }}
            />
          </AnimatePresence>
        )}
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

/** Preloads the stills so small orbs switch looks without flicker. */
export function OrbPreload() {
  return (
    <div aria-hidden className="hidden">
      {(["veille", "activation", "rubans", "tourbillon", "concentration", "impulsion", "ondes", "convergence", "lumiere", "coeur", "eclat", "calme"] as OrbLook[]).map((l) => (
        // eslint-disable-next-line @next/next/no-img-element
        <img key={l} src={still(l)} alt="" />
      ))}
    </div>
  );
}
