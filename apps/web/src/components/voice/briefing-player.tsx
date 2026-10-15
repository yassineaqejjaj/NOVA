"use client";

import { Button } from "@nova/ui";
import { Loader2, Square, Volume2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { defineMessages, useT } from "@/lib/i18n";
import { VoicePlayer } from "@/lib/voice/speaker";

const M = defineMessages({
  en: { listen: "Listen to my day", stop: "Stop", failed: "NOVA could not read your briefing aloud.", caption: "NOVA is speaking" },
  fr: { listen: "Écouter mon point du jour", stop: "Arrêter", failed: "NOVA n’a pas pu lire votre point du jour à voix haute.", caption: "NOVA parle" },
});

interface Briefing {
  lang: "fr" | "en";
  sentences: string[];
  withheld: number;
}

type Phase = "idle" | "loading" | "speaking";

/** « What matters today », read aloud sentence by sentence by NOVA's own voice (nothing classified is spelled out). */
export function BriefingPlayer() {
  const t = useT(M);
  const player = useRef<VoicePlayer | null>(null);
  const run = useRef(0); // incremented to cancel a briefing in progress
  const [phase, setPhase] = useState<Phase>("idle");
  const [caption, setCaption] = useState("");

  useEffect(() => {
    player.current = new VoicePlayer();
    return () => {
      run.current += 1;
      player.current?.stop();
    };
  }, []);

  const stop = useCallback(() => {
    run.current += 1;
    player.current?.stop();
    setPhase("idle");
    setCaption("");
  }, []);

  const start = useCallback(async () => {
    const mine = ++run.current;
    setPhase("loading");
    try {
      const briefing = await api.get<Briefing>("/today/briefing");
      for (const sentence of briefing.sentences) {
        if (run.current !== mine) return; // stopped meanwhile
        setPhase("speaking");
        setCaption(sentence);
        await player.current?.speak(sentence, briefing.lang, 1); // the server already left C2+ items out of the script
      }
    } catch {
      if (run.current === mine) toast(t("failed"));
    } finally {
      if (run.current === mine) {
        setPhase("idle");
        setCaption("");
      }
    }
  }, [t]);

  return (
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <Button
        type="button"
        variant="secondary"
        size="sm"
        className="rounded-full"
        onClick={phase === "idle" ? start : stop}
        aria-pressed={phase !== "idle"}
      >
        {phase === "loading" ? <Loader2 className="animate-spin" aria-hidden /> : phase === "speaking" ? <Square aria-hidden /> : <Volume2 aria-hidden />}
        {phase === "idle" ? t("listen") : t("stop")}
      </Button>
      <p className="min-h-5 text-[13px] text-muted" aria-live="polite" aria-label={caption ? t("caption") : undefined}>
        {caption}
      </p>
    </div>
  );
}
