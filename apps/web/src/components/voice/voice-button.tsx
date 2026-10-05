"use client";

import { Button, cn, Tooltip } from "@nova/ui";
import { useQuery } from "@tanstack/react-query";
import { Mic } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";
import { defineMessages, useT } from "@/lib/i18n";
import { voiceSupported } from "@/lib/voice/recorder";
import { useComposer, useUi } from "@/stores/ui";

const M = defineMessages({
  en: { talk: "Talk with NOVA" },
  fr: { talk: "Parler avec NOVA" },
});

export function useVoiceAvailable(): boolean {
  const [supported, setSupported] = useState(false);
  useEffect(() => setSupported(voiceSupported()), []);
  const { data } = useQuery({ queryKey: ["voice-status"], queryFn: () => api.get<{ enabled: boolean }>("/voice/status"), staleTime: 300_000, enabled: supported });
  return supported && !!data?.enabled;
}

/** Microphone button that opens the voice session (hidden when voice is unavailable). */
export function VoiceButton({ conversationId, className, size = "md" }: { conversationId?: string | null; className?: string; size?: "sm" | "md" }) {
  const t = useT(M);
  const available = useVoiceAvailable();
  const openVoice = useUi((s) => s.openVoice);
  const projectId = useComposer((s) => s.projectId);
  if (!available) return null;
  return (
    <Tooltip content={t("talk")}>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={t("talk")}
        onClick={() => openVoice({ conversationId, projectId })}
        className={cn("shrink-0 rounded-full text-muted hover:text-accent", size === "md" ? "size-10" : "size-8", className)}
      >
        <Mic className={size === "md" ? "!size-5" : "!size-4"} />
      </Button>
    </Tooltip>
  );
}
