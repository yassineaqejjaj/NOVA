"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { CommandPalette } from "@/components/shell/command-palette";
import { NovaMark } from "@/components/shell/nova-mark";
import { OrbPreload } from "@/components/shell/nova-orb";
import { VoiceSession } from "@/components/voice/voice-session";
import { MobileTabBar, Sidebar } from "@/components/shell/sidebar";
import { usePreferenceSync } from "@/hooks/use-preference-sync";
import { useMe } from "@/lib/api/hooks";
import { useUi } from "@/stores/ui";

function GlobalVoiceSession() {
  const voice = useUi((s) => s.voice);
  const closeVoice = useUi((s) => s.closeVoice);
  return (
    <VoiceSession
      open={voice.open}
      onOpenChange={(open) => !open && closeVoice()}
      conversationId={voice.conversationId}
      projectId={voice.projectId}
    />
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { data: me, isLoading } = useMe();
  const router = useRouter();
  usePreferenceSync(me);

  useEffect(() => {
    if (me && !me.preferences.onboarding_completed) router.replace("/welcome");
  }, [me, router]);

  if (isLoading || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <NovaMark phase="planning" size={36} />
      </div>
    );
  }
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <main className="min-w-0 flex-1 pb-16 md:pb-0">{children}</main>
      <MobileTabBar />
      <CommandPalette />
      <OrbPreload />
      <GlobalVoiceSession />
    </div>
  );
}
