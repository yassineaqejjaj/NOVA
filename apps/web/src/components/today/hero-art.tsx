"use client";

import { motion } from "framer-motion";

/** Generated hero scene (no stock photo): warm sky, layered ridges and NOVA's glowing orb. */
export function HeroArt({ className }: { className?: string }) {
  return (
    <div className={className} aria-hidden>
      <svg viewBox="0 0 640 320" preserveAspectRatio="xMidYMid slice" className="size-full">
        <defs>
          <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#fbe3e2" />
            <stop offset="55%" stopColor="#f7c9cf" />
            <stop offset="100%" stopColor="#f3d9d3" />
          </linearGradient>
          <radialGradient id="sun" cx="0.62" cy="0.42" r="0.45">
            <stop offset="0%" stopColor="#fff6f2" stopOpacity="0.95" />
            <stop offset="40%" stopColor="#ffd2d6" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#ffd2d6" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="ridge1" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#e9a7b0" />
            <stop offset="100%" stopColor="#d98d98" />
          </linearGradient>
          <linearGradient id="ridge2" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#c97884" />
            <stop offset="100%" stopColor="#a85d6b" />
          </linearGradient>
          <linearGradient id="ridge3" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#7c4250" />
            <stop offset="100%" stopColor="#4b2632" />
          </linearGradient>
        </defs>
        <rect width="640" height="320" fill="url(#sky)" />
        <rect width="640" height="320" fill="url(#sun)" />
        <path d="M0 210 L80 170 L150 196 L240 140 L320 182 L400 150 L480 176 L560 132 L640 168 L640 320 L0 320 Z" fill="url(#ridge1)" opacity="0.75" />
        <path d="M0 246 L90 214 L170 238 L260 196 L350 236 L430 204 L520 236 L640 200 L640 320 L0 320 Z" fill="url(#ridge2)" opacity="0.85" />
        <path d="M0 290 L120 254 L210 276 L300 246 L380 270 L470 250 L560 280 L640 262 L640 320 L0 320 Z" fill="url(#ridge3)" />
      </svg>
      <motion.div
        className="absolute left-[68%] top-[18%] size-[120px] -translate-x-1/2 rounded-full"
        style={{
          background: "radial-gradient(circle at 34% 30%, #fff 0%, #ffe5ec 22%, #f9a8bf 48%, #f0463c 82%, #b91c3c 100%)",
          boxShadow: "0 0 60px 18px rgb(244 114 140 / 0.45), 0 0 140px 50px rgb(255 214 222 / 0.5)",
        }}
        animate={{ y: [0, -6, 0] }}
        transition={{ duration: 6, repeat: Infinity, ease: "easeInOut" }}
      />
    </div>
  );
}
