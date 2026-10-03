"use client";

import { Skeleton } from "@nova/ui";
import { useEffect, useRef } from "react";

import { Composer } from "@/components/composer/composer";
import { useExecutionStream } from "@/hooks/use-execution-stream";
import { useConversation, useMe, useProjects, useSendIntent } from "@/lib/api/hooks";
import type { Message } from "@/lib/api/types";
import { useComposer } from "@/stores/ui";

import { NovaMessage, UserMessage } from "./message";

function LiveStream({ conversationId, message }: { conversationId: string; message: Message }) {
  useExecutionStream(conversationId, message.task?.id, message.task?.status);
  return null;
}

export function ConversationView({ conversationId, activeArtifactId, onOpenArtifact }: { conversationId: string; activeArtifactId?: string | null; onOpenArtifact: (id: string) => void }) {
  const { data: conversation, isLoading } = useConversation(conversationId);
  const { data: me } = useMe();
  const send = useSendIntent();
  const { data: projects } = useProjects();
  const setProject = useComposer((s) => s.setProject);
  const bottom = useRef<HTMLDivElement>(null);
  const messages = conversation?.messages ?? [];
  const lastBlocks = messages.at(-1)?.blocks.length ?? 0;

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, lastBlocks]);

  useEffect(() => {
    if (conversation?.project_id) setProject(conversation.project_id);
  }, [conversation?.project_id, setProject]);

  const project = projects?.find((p) => p.id === conversation?.project_id);
  const busy = messages.some((m) => m.task && ["queued", "running"].includes(m.task.status));

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-[760px] space-y-6">
          {isLoading ? (
            <div className="space-y-3">
              <Skeleton className="ml-auto h-10 w-1/2" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : null}
          {messages.map((m, index) =>
            m.role === "user" ? (
              <UserMessage key={m.id} message={m} />
            ) : (
              <NovaMessage key={m.id} message={m} novaName={me?.preferences.nova_name ?? "NOVA"} ctx={{
                  conversationId,
                  onOpenArtifact,
                  projectOrbitUrl: project?.orbit_url,
                  requestText: messages[index - 1]?.role === "user" ? messages[index - 1]?.meta.text : undefined,
                  resend: async (text) => {
                    await send.mutateAsync({ conversationId, payload: { text, project_id: conversation?.project_id ?? null, active_artifact_id: activeArtifactId ?? null } });
                  },
                }}
              />
            ),
          )}
          {messages.filter((m) => m.role === "nova" && m.task).map((m) => (
            <LiveStream key={m.id} conversationId={conversationId} message={m} />
          ))}
          <div ref={bottom} />
        </div>
      </div>
      <div className="border-t border-border bg-background/80 px-6 py-4 backdrop-blur">
        <div className="mx-auto max-w-[760px]">
          <Composer conversationId={conversationId} activeArtifactId={activeArtifactId} compact placeholder={busy ? "NOVA is working — you can keep writing…" : undefined} />
        </div>
      </div>
    </div>
  );
}
