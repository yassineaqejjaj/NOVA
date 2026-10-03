"use client";

import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { keys } from "@/lib/api/hooks";
import type { Block, Conversation, ExecutionEvent, TaskStatus } from "@/lib/api/types";
import { useNovaState } from "@/stores/ui";

const LIVE: TaskStatus[] = ["queued", "running"];

function refreshAfterExecution(client: QueryClient, conversationId: string) {
  void client.invalidateQueries({ queryKey: keys.conversation(conversationId) });
  void client.invalidateQueries({ queryKey: ["tasks"] });
  void client.invalidateQueries({ queryKey: ["artifact"] });
  void client.invalidateQueries({ queryKey: ["artifacts"] });
  void client.invalidateQueries({ queryKey: ["artifact-versions"] });
  void client.invalidateQueries({ queryKey: keys.today });
}

/**
 * Follow a task's execution over SSE and apply real events to the conversation cache: blocks are upserted by
 * key, the NOVA state indicator follows ``status`` events. Nothing is simulated.
 *
 * Once opened, the stream stays open until ``done`` / ``end`` — status updates carried by the stream itself
 * must not close it (they arrive just before ``done``). It reopens when the task becomes live again (resume).
 */
export function useExecutionStream(conversationId: string | null, taskId: string | null | undefined, status?: TaskStatus) {
  const client = useQueryClient();
  const setPhase = useNovaState((s) => s.setPhase);
  const clear = useNovaState((s) => s.clear);
  const lastSeq = useRef(0);
  const [streaming, setStreaming] = useState(false);

  useEffect(() => {
    if (status && LIVE.includes(status)) setStreaming(true);
  }, [status]);

  useEffect(() => {
    if (!conversationId || !taskId || !streaming) return;
    const source = new EventSource(`/api/v1/executions/${taskId}/events?after=${lastSeq.current}`, { withCredentials: true });
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      clear(taskId);
      source.close();
      refreshAfterExecution(client, conversationId);
      setStreaming(false);
    };

    const apply = (event: ExecutionEvent) => {
      if (event.seq) lastSeq.current = Math.max(lastSeq.current, event.seq);
      if (event.type === "status" && event.phase) setPhase(taskId, event.phase, String(event.label ?? ""));
      if (event.type === "block" && event.block && event.message_id) {
        const block = event.block as Block;
        client.setQueryData<Conversation>(keys.conversation(conversationId), (old) => {
          if (!old?.messages) return old;
          return {
            ...old,
            messages: old.messages.map((m) => {
              if (m.id !== event.message_id) return m;
              const others = m.blocks.filter((b) => b.key !== block.key);
              return { ...m, blocks: [...others, block].sort((a, b) => a.position - b.position) };
            }),
          };
        });
      }
      // Only task-level status changes (step updates carry `step` / `step_status`).
      if (event.type === "task" && event.status && !event.step) {
        client.setQueryData<Conversation>(keys.conversation(conversationId), (old) =>
          old?.messages
            ? {
                ...old,
                messages: old.messages.map((m) =>
                  m.task?.id === taskId ? { ...m, task: { ...m.task, status: event.status as TaskStatus } } : m,
                ),
              }
            : old,
        );
      }
      if (event.type === "done") finish();
    };

    for (const type of ["status", "progress", "block", "task", "done", "error"]) {
      source.addEventListener(type, (e) => apply(JSON.parse((e as MessageEvent).data) as ExecutionEvent));
    }
    source.addEventListener("end", finish);
    return () => source.close();
  }, [client, conversationId, taskId, streaming, setPhase, clear]);
}
