"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

import { ArtifactPanel } from "@/components/artifact/artifact-panel";
import { ConversationView } from "@/components/conversation/conversation-view";
import { SplitWorkspace } from "@/components/shell/split";
import { useConversation } from "@/lib/api/hooks";

function Workspace() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const artifactId = params.get("artifact");
  const { data: conversation } = useConversation(id);
  const autoOpened = useRef<string | null>(null);

  const open = (artifact: string | null) => router.replace(artifact ? `/c/${id}?artifact=${artifact}` : `/c/${id}`, { scroll: false });

  // Open the Artifact NOVA just created (once per Artifact), so the work appears next to the conversation.
  useEffect(() => {
    const last = conversation?.messages?.at(-1);
    const block = last?.blocks.find((b) => b.type === "artifact");
    const created = block?.data as { artifact_id?: string } | undefined;
    if (created?.artifact_id && autoOpened.current !== created.artifact_id && !artifactId) {
      autoOpened.current = created.artifact_id;
      open(created.artifact_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversation?.messages?.length, conversation?.messages?.at(-1)?.blocks.length]);

  return (
    <SplitWorkspace
      left={<ConversationView conversationId={id} activeArtifactId={artifactId} onOpenArtifact={(a) => open(a)} />}
      right={artifactId ? <ArtifactPanel key={artifactId} artifactId={artifactId} onClose={() => open(null)} /> : null}
    />
  );
}

export default function ConversationPage() {
  return (
    <Suspense>
      <Workspace />
    </Suspense>
  );
}
