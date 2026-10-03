"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useRef, useState } from "react";

/** Conversation | Artifact split workspace with a draggable divider. */
export function SplitWorkspace({ left, right }: { left: React.ReactNode; right: React.ReactNode | null }) {
  const [ratio, setRatio] = useState(0.42);
  const container = useRef<HTMLDivElement>(null);
  const onPointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    const move = (ev: PointerEvent) => {
      const rect = container.current?.getBoundingClientRect();
      if (!rect) return;
      setRatio(Math.min(0.7, Math.max(0.28, (ev.clientX - rect.left) / rect.width)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }, []);

  return (
    <div ref={container} className="flex h-screen min-w-0">
      <div className="min-w-0" style={{ width: right ? `${ratio * 100}%` : "100%" }}>
        {left}
      </div>
      <AnimatePresence>
        {right ? (
          <>
            <div
              role="separator"
              aria-orientation="vertical"
              onPointerDown={onPointerDown}
              className="w-1 shrink-0 cursor-col-resize bg-border transition-colors hover:bg-accent/40"
            />
            <motion.div
              initial={{ opacity: 0, x: 24 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 24 }}
              transition={{ duration: 0.22, ease: "easeOut" }}
              className="min-w-0 flex-1 bg-background"
            >
              {right}
            </motion.div>
          </>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
