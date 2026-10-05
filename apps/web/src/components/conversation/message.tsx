"use client";

import { Button, cn, Popover, PopoverContent, PopoverTrigger, Textarea, Tooltip } from "@nova/ui";
import { useMutation } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Paperclip, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { NovaMark } from "@/components/shell/nova-mark";
import { api } from "@/lib/api/client";
import type { Message, NovaPhase } from "@/lib/api/types";
import { clock } from "@/lib/format";
import { defineMessages, type Lang, useLang, useT } from "@/lib/i18n";

import { type BlockContext, BlockView } from "./blocks";
import { knownSystemLabel } from "./blocks.messages";

const M = defineMessages({
  en: {
    thanks: "Thanks — NOVA will learn from this.",
    useful: "Useful",
    notUseful: "Not useful",
    improve: "What should NOVA improve?",
    optional: "Optional",
    send: "Send",
    starting: "Starting",
    waitingForYou: "Waiting for you",
    understanding: "Understanding your request…",
    traceHint: "Trace ID — use it to find this execution in your observability stack or FORGE",
  },
  fr: {
    thanks: "Merci — NOVA en tiendra compte.",
    useful: "Utile",
    notUseful: "Pas utile",
    improve: "Que devrait améliorer NOVA ?",
    optional: "Facultatif",
    send: "Envoyer",
    starting: "Démarrage",
    waitingForYou: "En attente de votre retour",
    understanding: "Analyse de votre demande…",
    traceHint: "ID de trace — utilisez-le pour retrouver cette exécution dans votre outil d’observabilité ou dans FORGE",
  },
});

const PHASES: Record<Lang, Record<NovaPhase, string>> = {
  en: {
    idle: "Idle",
    retrieving_context: "Retrieving context",
    planning: "Planning",
    executing: "Executing",
    waiting_user: "Waiting for you",
    completed: "Completed",
    failed: "Failed",
  },
  fr: {
    idle: "Inactif",
    retrieving_context: "Récupération du contexte",
    planning: "Planification",
    executing: "Exécution",
    waiting_user: "En attente de votre retour",
    completed: "Terminé",
    failed: "Échec",
  },
};

export function UserMessage({ message }: { message: Message }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18 }} className="flex justify-end">
      <div className="max-w-[85%] rounded-[14px] bg-surface-2 px-4 py-2.5 text-[14.5px] leading-relaxed text-text">
        <p className="whitespace-pre-wrap">{message.meta.text}</p>
        {message.meta.attachments?.length ? (
          <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11.5px] text-subtle">
            {message.meta.attachments.map((a) => (
              <span key={a} className="inline-flex items-center gap-1"><Paperclip className="size-3" />{a}</span>
            ))}
          </div>
        ) : null}
      </div>
    </motion.div>
  );
}

function Feedback({ message }: { message: Message }) {
  const [rating, setRating] = useState<"useful" | "not_useful" | null>(null);
  const [comment, setComment] = useState("");
  const [open, setOpen] = useState(false);
  const t = useT(M);
  const submit = useMutation({
    mutationFn: (body: { rating: "useful" | "not_useful"; comment?: string }) =>
      api.post("/feedback", { ...body, message_id: message.id, task_id: message.task?.id }),
    onSuccess: (_, body) => {
      setRating(body.rating);
      setOpen(false);
      toast(t("thanks"));
    },
  });
  return (
    <div className="flex items-center gap-0.5">
      <Tooltip content={t("useful")}>
        <Button variant="ghost" size="icon" className={cn("size-7", rating === "useful" && "text-success")} onClick={() => submit.mutate({ rating: "useful" })} aria-label={t("useful")}>
          <ThumbsUp className="!size-3.5" />
        </Button>
      </Tooltip>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="icon" className={cn("size-7", rating === "not_useful" && "text-danger")} aria-label={t("notUseful")}>
            <ThumbsDown className="!size-3.5" />
          </Button>
        </PopoverTrigger>
        <PopoverContent>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit.mutate({ rating: "not_useful", comment: comment || undefined });
            }}
            className="space-y-2"
          >
            <div className="text-[13px] font-medium">{t("improve")}</div>
            <Textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} placeholder={t("optional")} />
            <div className="flex justify-end">
              <Button type="submit" size="sm" variant="primary" disabled={submit.isPending}>{t("send")}</Button>
            </div>
          </form>
        </PopoverContent>
      </Popover>
    </div>
  );
}

export function NovaMessage({ message, ctx, novaName }: { message: Message; ctx: Omit<BlockContext, "taskId" | "waiting">; novaName: string }) {
  const t = useT(M);
  const lang = useLang();
  const task = message.task;
  const live = !!task && ["queued", "running"].includes(task.status);
  const waiting = task?.status === "waiting_user";
  const blockCtx: BlockContext = { ...ctx, taskId: task?.id ?? null, waiting, taskStatus: task?.status };
  const empty = message.blocks.length === 0;
  // The API's phase label is English system text: shown as is in English, translated when known, else the generic phase.
  const phase = (current: NonNullable<Message["task"]>) => (current.phase_label && knownSystemLabel(current.phase_label, lang)) || PHASES[lang][current.phase];
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="flex gap-3">
      <div className="pt-0.5">
        <NovaMark phase={live ? (task!.phase === "idle" ? "planning" : task!.phase) : waiting ? "waiting_user" : "idle"} size={20} />
      </div>
      <div className="min-w-0 flex-1 space-y-2.5">
        <div className="flex items-center gap-2 text-[12px] text-subtle">
          <span className="font-medium text-muted">{novaName}</span>
          <span>{clock(message.created_at)}</span>
          {live ? <span className="text-accent">· {task!.phase === "idle" ? t("starting") : phase(task!)}</span> : null}
          {waiting ? <span className="text-warning">· {t("waitingForYou")}</span> : null}
        </div>
        {empty && live ? <div className="text-[13.5px] text-subtle">{t("understanding")}</div> : null}
        {message.blocks.map((block) => (
          <BlockView key={block.key} block={block} ctx={blockCtx} live={live} />
        ))}
        {task && ["completed", "failed"].includes(task.status) ? (
          <div className="flex items-center gap-2 pt-0.5">
            <Feedback message={message} />
            {task.trace_id ? (
              <Tooltip content={t("traceHint")}>
                <span className="cursor-default font-mono text-[10.5px] text-subtle/70">{task.trace_id.slice(0, 12)}</span>
              </Tooltip>
            ) : null}
          </div>
        ) : null}
      </div>
    </motion.div>
  );
}
