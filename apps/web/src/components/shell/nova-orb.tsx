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

// --- Footage: public/orb/orb.mp4 — one segment per state (ping-pong loops encoded in the file) -----------

const VIDEO = "/orb/orb.mp4";
// Frame-exact boundaries of public/orb/orb.mp4 (24 fps; regenerate with infrastructure/orb/build_orb_assets.py).
const SEGMENTS = {
  idle: [0, 1.4167],
  thinking: [1.4167, 5.8333],
  working: [5.8333, 9.8333],
  waiting: [9.8333, 11.8333],
  clarification: [11.8333, 14.1667],
  completed: [14.1667, 17.75], // one shot: impulsion → lumière blanche → cœur doré → éclat final → retour au calme
  calm: [17.75, 19.1],
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
  thinking: { looks: ["activation", "rubans"], step: 1400, loop: true },
  working: { looks: ["tourbillon", "concentration", "convergence"], step: 1600, loop: true },
  waiting: { looks: ["activation", "veille"], step: 2000, loop: true },
  clarification: { looks: ["ondes", "activation"], step: 1500, loop: true },
  completed: { looks: ["impulsion", "lumiere", "coeur", "eclat", "calme"], step: 650, loop: false },
  listening: { looks: ["activation"], step: 0, loop: false },
  speaking: { looks: ["ondes", "convergence"], step: 900, loop: true },
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

/** Plays the state's segment of the footage in a loop (completed: once, then the calm loop). */
function useSegmentPlayer(video: React.RefObject<HTMLVideoElement | null>, state: OrbState, enabled: boolean) {
  const first = useRef(true);
  useEffect(() => {
    const el = video.current;
    if (!el || !enabled) return;
    const isFirst = first.current;
    first.current = false;
    let segment: Segment = state === "completed" && isFirst ? "calm" : STATE_SEGMENT[state];
    let frame = 0;
    const start = () => {
      el.currentTime = SEGMENTS[segment][0];
      void el.play().catch(() => undefined); // autoplay can be refused (power saving): the poster stays visible
    };
    const tick = () => {
      const [from, to] = SEGMENTS[segment];
      if (el.currentTime >= to - 0.05 || el.currentTime < from - 0.25) {
        if (segment === "completed") segment = "calm";
        el.currentTime = SEGMENTS[segment][0];
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
      el.removeEventListener("loadedmetadata", start);
      el.removeEventListener("ended", onEnded);
    };
  }, [video, state, enabled]);
}

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
  useSegmentPlayer(video, state, useVideo);

  const haloColor = state === "waiting" ? "245 158 11" : state === "clarification" ? "168 85 247" : palette.glow;
  const haloOpacity = state === "working" || state === "speaking" ? 0.4 : state === "idle" ? 0.16 : 0.28;
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
      <motion.span
        className="absolute rounded-full"
        style={{ inset: -size * (size >= 44 ? 0.24 : 0.18), background: `radial-gradient(circle, rgb(${haloColor} / ${haloOpacity}), transparent 68%)` }}
        animate={reduce ? undefined : { scale: [0.94, 1.1, 0.94], opacity: [0.9, 0.5, 0.9] }}
        transition={{ duration: state === "working" ? 1.4 : state === "idle" ? 6 : 2.6, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.span
        className="relative block size-full"
        style={{ filter: palette.filter === "none" ? undefined : palette.filter }}
        animate={reduce || useVideo ? undefined : { scale: state === "idle" ? [1, 1.015, 1] : [1, 1.035, 1] }}
        transition={{ duration: state === "idle" ? 6 : 2, repeat: Infinity, ease: "easeInOut" }}
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
              transition={{ duration: 0.45 }}
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
